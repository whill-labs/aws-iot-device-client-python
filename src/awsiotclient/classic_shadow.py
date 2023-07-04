from concurrent.futures import Future
from traceback import format_exc
from typing import Callable

from awscrt import mqtt
from awsiot import iotshadow

from . import get_module_logger
from .shadow import (
    done_future,
    ShadowDocument,
    ExceptionAwsIotShadow,
    ExceptionAwsIotShadowInvalidDelta,
    ShadowClientCommon,
)

logger = get_module_logger(__name__)


ExceptionAwsIotClassicShadow = ExceptionAwsIotShadow
ExceptionAwsIotClassicShadowInvalidDelta = ExceptionAwsIotShadowInvalidDelta


def empty_func(thing_name: str, shadow_property: str, value: ShadowDocument) -> None:
    logger.debug(
        f"empty func. thing_name: {thing_name}, property: {shadow_property}, value: {value}"
    )


class client(ShadowClientCommon):
    def __init__(
        self,
        connection: mqtt.Connection,
        thing_name: str,
        shadow_property: str,
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
        delta_func: Callable[[str, str, ShadowDocument], None] = empty_func,
        desired_func: Callable[[str, str, ShadowDocument], None] = empty_func,
        publish_full_doc: bool = False,
    ) -> None:
        super().__init__(
            connection=connection,
            thing_name=thing_name,
            property_name=shadow_property,
            qos=qos,
            delta_func=delta_func,
            desired_func=desired_func,
            publish_full_doc=publish_full_doc,
        )

        try:
            # Subscribe to necessary topics.
            # Note that **is** important to wait for "accepted/rejected" subscriptions
            # to succeed before publishing the corresponding "request".
            logger.debug("Subscribing to Delta events...")
            self.client.subscribe_to_shadow_delta_updated_events(
                request=iotshadow.ShadowDeltaUpdatedSubscriptionRequest(
                    thing_name=thing_name
                ),
                qos=qos,
                callback=self.on_shadow_delta_updated,
            )[0].result()

            self.__subscribe_update_shadow()
            self.__subscribe_get_shadow()

            # Issue request for shadow's current state.
            # The response will be received by the on_get_accepted() callback
            logger.debug("Requesting current shadow state...")
            self.client.publish_get_shadow(
                request=iotshadow.GetShadowRequest(thing_name=thing_name),
                qos=qos,
            ).result()

        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def __subscribe_update_shadow(self) -> None:
        logger.debug("Subscribing to Update responses...")
        request = iotshadow.UpdateShadowSubscriptionRequest(thing_name=self.thing_name)
        accepted_future, _ = self.client.subscribe_to_update_shadow_accepted(
            request=request,
            qos=self.qos,
            callback=self.on_update_shadow_accepted,
        )

        rejected_future, _ = self.client.subscribe_to_update_shadow_rejected(
            request=request,
            qos=self.qos,
            callback=self.on_update_shadow_rejected,
        )

        accepted_future.result()
        rejected_future.result()

    def __subscribe_get_shadow(self) -> None:
        logger.debug("Subscribing to Get responses...")
        request = iotshadow.GetShadowSubscriptionRequest(thing_name=self.thing_name)
        accepted_future, _ = self.client.subscribe_to_get_shadow_accepted(
            request=request,
            qos=self.qos,
            callback=self.on_get_shadow_accepted,
        )

        rejected_future, _ = self.client.subscribe_to_get_shadow_rejected(
            request=request,
            qos=self.qos,
            callback=self.on_get_shadow_rejected,
        )

        accepted_future.result()
        rejected_future.result()

    def update_shadow_request(
        self, desired: ShadowDocument, reported: ShadowDocument
    ) -> "Future[None]":
        if desired is None and reported is None:
            return done_future()

        desired = None if desired is None else {self.property_name: desired}
        reported = None if reported is None else {self.property_name: reported}

        request = iotshadow.UpdateShadowRequest(
            thing_name=self.thing_name,
            state=iotshadow.ShadowState(
                desired=desired,
                reported=reported,
            ),
        )
        future: "Future[None]" = self.client.publish_update_shadow(request, self.qos)
        future.add_done_callback(self.on_publish_update_shadow)
        return future
