import threading
from concurrent.futures import Future
from traceback import format_exc
from typing import Any, Callable, Dict, Optional

from awscrt import mqtt
from awsiot import iotshadow

from . import ExceptionAwsIotClient, dictdiff, get_module_logger

logger = get_module_logger(__name__)
ShadowDocument = Optional[Dict[str, Any]]


class ExceptionAwsIotClassicShadow(ExceptionAwsIotClient):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ExceptionAwsIotClassicShadowInvalidDelta(ExceptionAwsIotClassicShadow):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


def empty_func(thing_name: str, shadow_property: str, value: ShadowDocument) -> None:
    logger.debug(f"empty func. thing_name: {thing_name}, property: {shadow_property}, value: {value}")


SHADOW_VALUE_DEFAULT = None


class LockedData:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.shadow_value: ShadowDocument = None
        self.desired_value: ShadowDocument = None
        self.disconnect_called: bool = False


class client:
    def __init__(
        self,
        connection: mqtt.Connection,
        thing_name: str,
        shadow_property: str,
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
        delta_func: Callable[[str, str, ShadowDocument], None] = empty_func,
        publish_full_doc: bool = False,
    ) -> None:
        self.client = iotshadow.IotShadowClient(connection)
        self.thing_name = thing_name
        self.shadow_property = shadow_property
        self.locked_data = LockedData()
        self.delta_func = delta_func
        self.qos = qos
        self.publish_full_doc = publish_full_doc
        try:
            # Subscribe to necessary topics.
            # Note that **is** important to wait for "accepted/rejected" subscriptions
            # to succeed before publishing the corresponding "request".
            logger.debug("Subscribing to Delta events...")
            (delta_subscribed_future, _,) = self.client.subscribe_to_shadow_delta_updated_events(
                request=iotshadow.ShadowDeltaUpdatedSubscriptionRequest(thing_name=thing_name),
                qos=qos,
                callback=self.on_shadow_delta_updated,
            )

            # Wait for subscription to succeed
            delta_subscribed_future.result()

            logger.debug("Subscribing to Update responses...")
            (update_accepted_subscribed_future, _,) = self.client.subscribe_to_update_shadow_accepted(
                request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=thing_name),
                qos=qos,
                callback=self.on_update_shadow_accepted,
            )

            (update_rejected_subscribed_future, _,) = self.client.subscribe_to_update_shadow_rejected(
                request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=thing_name),
                qos=qos,
                callback=self.on_update_shadow_rejected,
            )

            # Wait for subscriptions to succeed
            update_accepted_subscribed_future.result()
            update_rejected_subscribed_future.result()

            logger.debug("Subscribing to Get responses...")
            (get_accepted_subscribed_future, _,) = self.client.subscribe_to_get_shadow_accepted(
                request=iotshadow.GetShadowSubscriptionRequest(thing_name=thing_name),
                qos=qos,
                callback=self.on_get_shadow_accepted,
            )

            (get_rejected_subscribed_future, _,) = self.client.subscribe_to_get_shadow_rejected(
                request=iotshadow.GetShadowSubscriptionRequest(thing_name=thing_name),
                qos=qos,
                callback=self.on_get_shadow_rejected,
            )

            # Wait for subscriptions to succeed
            get_accepted_subscribed_future.result()
            get_rejected_subscribed_future.result()

            # The rest of the sample runs asyncronously.

            # Issue request for shadow's current state.
            # The response will be received by the on_get_accepted() callback
            logger.debug("Requesting current shadow state...")
            publish_get_future = self.client.publish_get_shadow(
                request=iotshadow.GetShadowRequest(thing_name=thing_name), qos=qos
            )

            # Ensure that publish succeeds
            publish_get_future.result()

        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def on_get_shadow_accepted(self, response):
        # type: (iotshadow.GetShadowResponse) -> None
        try:
            logger.debug("Finished getting initial shadow state.")

            with self.locked_data.lock:
                if self.locked_data.shadow_value is not None:
                    logger.debug("  Ignoring initial query because a delta event has already been received.")
                    return

            if response.state:
                if response.state.delta:
                    value = response.state.delta.get(self.shadow_property)
                    if value:
                        logger.debug("  Shadow contains delta value '{}'.".format(value))
                        return

                if response.state.reported:
                    value = response.state.reported.get(self.shadow_property)
                    if value:
                        logger.debug("  Shadow contains reported value '{}'.".format(value))
                        self.set_local_value_due_to_initial_query(response.state.reported[self.shadow_property])
                        return

            logger.debug("  Shadow document lacks '{}' property. Setting defaults...".format(self.shadow_property))
            self.change_reported_value(SHADOW_VALUE_DEFAULT)
            return

        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def on_get_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        if error.code == 404:
            logger.debug("Thing has no shadow document. Creating with defaults...")
            self.change_reported_value(SHADOW_VALUE_DEFAULT)
        else:
            raise ExceptionAwsIotClassicShadow(
                "Get request was rejected. code:{} message:'{}'".format(error.code, error.message)
            )

    def on_shadow_delta_updated(self, delta):
        # type: (iotshadow.ShadowDeltaUpdatedEvent) -> None
        try:
            logger.debug("Received shadow delta event.")
            if delta.state and (self.shadow_property in delta.state):
                value = delta.state[self.shadow_property]
                if value is None:
                    logger.debug("  Delta reports that '{}' was deleted. Resetting defaults...".format(self.shadow_property))
                    self.change_reported_value(SHADOW_VALUE_DEFAULT)
                    return
                else:
                    logger.debug("  Delta reports that desired value is '{}'. Invoke delta func...".format(value))
                    try:
                        self.delta_func(self.thing_name, self.shadow_property, value)
                    except ExceptionAwsIotClassicShadowInvalidDelta:
                        logger.debug(
                            "  Delta reports invalid request in {}. Resetting defaults...".format(self.shadow_property)
                        )
                        self.change_desired_value(SHADOW_VALUE_DEFAULT)
            else:
                logger.debug("  Delta did not report a change in '{}'".format(self.shadow_property))

        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def on_publish_update_shadow(self, future: Future) -> None:  # type: ignore
        try:
            future.result()
            logger.debug("Update request published.")
        except Exception as e:
            logger.error(format_exc())
            logger.debug("Failed to publish update request.")
            raise (e)

    def on_update_shadow_accepted(self, response):
        # type: (iotshadow.UpdateShadowResponse) -> None
        try:
            if response.state.reported:
                logger.debug("Finished updating reported shadow value to '{}'.".format(response.state.reported))
            if response.state.desired:
                logger.debug("Finished updating desired shadow value to '{}'.".format(response.state.desired))
        except Exception as e:
            logger.error(format_exc())
            logger.error("Updated shadow is missing the target property.")
            raise (e)

    def on_update_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        errstr = "Update request was rejected. code:{} message:'{}'".format(error.code, error.message)
        logger.error(errstr)
        raise ExceptionAwsIotClient(errstr)

    def set_local_value_due_to_initial_query(self, reported_value: ShadowDocument) -> None:
        with self.locked_data.lock:
            self.locked_data.shadow_value = reported_value

    def change_reported_value(self, value: ShadowDocument) -> None:
        with self.locked_data.lock:
            if self.locked_data.shadow_value == value:
                logger.debug("Local value is already '{}'.".format(value))
                return

            if self.publish_full_doc:
                reported = value
            else:
                reported = dictdiff.dictdiff(self.locked_data.shadow_value, value)

            logger.debug("Changed local shadow value to '{}'.".format(value))
            self.locked_data.shadow_value = value

        logger.debug("Updating reported shadow value to '{}'...".format(reported))
        request = iotshadow.UpdateShadowRequest(
            thing_name=self.thing_name,
            state=iotshadow.ShadowState(
                reported={self.shadow_property: reported},
            ),
        )
        future = self.client.publish_update_shadow(request, self.qos)
        future.add_done_callback(self.on_publish_update_shadow)

    def change_desired_value(self, value: ShadowDocument) -> None:
        with self.locked_data.lock:
            if self.locked_data.desired_value == value:
                logger.debug("Local desired value is already '{}'.".format(value))
                return

            if self.publish_full_doc:
                desired = value
            else:
                desired = dictdiff.dictdiff(self.locked_data.desired_value, value)

            logger.debug("Changed local desired value to '{}'.".format(value))
            self.locked_data.desired_value = value

        logger.debug("Updating desired shadow value to '{}'...".format(desired))
        request = iotshadow.UpdateShadowRequest(
            thing_name=self.thing_name,
            state=iotshadow.ShadowState(
                desired={self.shadow_property: desired},
            ),
        )
        future = self.client.publish_update_shadow(request, self.qos)
        future.add_done_callback(self.on_publish_update_shadow)
