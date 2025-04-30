from abc import ABC, abstractmethod
from concurrent.futures import Future
from dataclasses import dataclass, field
from threading import Lock
from traceback import format_exc
from typing import Any, Callable, Dict, Optional, Tuple, Union

from awscrt import mqtt
from awsiot import iotshadow

from . import ExceptionAwsIotClient, dictdiff, get_module_logger

logger = get_module_logger(__name__)
ShadowDocument = Optional[Dict[str, Any]]
SHADOW_VALUE_DEFAULT = None


class ExceptionAwsIotShadow(ExceptionAwsIotClient):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ExceptionAwsIotShadowInvalidDelta(ExceptionAwsIotShadow):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


def done_future() -> "Future[None]":
    future: "Future[None]" = Future()
    future.set_result(None)
    return future


@dataclass
class DocumentTracker:
    _current: ShadowDocument = None

    def get(self) -> ShadowDocument:
        return self._current

    def set(self, value: ShadowDocument) -> None:
        self._current = value

    def update(self, new: ShadowDocument, diff_only: bool) -> ShadowDocument:
        if self._current == new:
            logger.debug(f"Shadow value is already '{new}'.")
            return None

        if diff_only:
            value = dictdiff.dictdiff(self._current, new)
        else:
            value = new

        logger.debug(f"Shadow value changes to '{new}'.")
        self.set(new)
        return value


@dataclass
class ShadowData:
    _lock: Lock = Lock()
    _desired_value: DocumentTracker = field(default_factory=DocumentTracker)
    _reported_value: DocumentTracker = field(default_factory=DocumentTracker)

    def get_desired_value(self) -> ShadowDocument:
        with self._lock:
            return self._desired_value.get()

    def set_desired_value(self, value: ShadowDocument) -> None:
        with self._lock:
            self._desired_value.set(value)

    def update_desired_value(
        self, value: ShadowDocument, publish_full_doc: bool
    ) -> ShadowDocument:
        with self._lock:
            return self._desired_value.update(value, not publish_full_doc)

    def get_reported_value(self) -> ShadowDocument:
        with self._lock:
            return self._reported_value.get()

    def set_reported_value(self, value: ShadowDocument) -> None:
        with self._lock:
            self._reported_value.set(value)

    def update_reported_value(
        self, value: ShadowDocument, publish_full_doc: bool
    ) -> ShadowDocument:
        with self._lock:
            return self._reported_value.update(value, not publish_full_doc)

    def update_both_values(
        self,
        desired_value: ShadowDocument,
        reported_value: ShadowDocument,
        publish_full_doc: bool,
    ) -> Tuple[ShadowDocument, ShadowDocument]:
        with self._lock:
            desired = self._desired_value.update(desired_value, not publish_full_doc)
            reported = self._reported_value.update(reported_value, not publish_full_doc)
            return desired, reported


class ShadowClientCommon(ABC):
    client: iotshadow.IotShadowClient
    thing_name: str
    property_name: Optional[str]
    locked_data = ShadowData()
    qos: mqtt.QoS
    publish_full_doc: bool

    def __init__(
        self,
        connection: mqtt.Connection,
        thing_name: str,
        property_name: Optional[str],
        qos: mqtt.QoS,
        delta_func: Callable[[str, str, ShadowDocument], None],
        desired_func: Callable[[str, str, ShadowDocument], None],
        publish_full_doc: bool,
    ) -> None:
        self.client = iotshadow.IotShadowClient(connection)
        self.thing_name = thing_name
        self.property_name = property_name
        self.qos = qos
        self.delta_func = delta_func
        self.desired_func = desired_func
        self.publish_full_doc = publish_full_doc

    def __filter_property(self, v: ShadowDocument) -> ShadowDocument:
        if self.property_name is None:
            return v
        return v.get(self.property_name)

    def label(self) -> str:
        return self.property_name

    def on_shadow_delta_updated(self, delta: iotshadow.ShadowDeltaUpdatedEvent) -> None:
        logger.debug("Received shadow delta event.")
        if not delta.state:
            logger.debug(f"  Delta did not report a change in '{self.label()}'")
            return

        value = self.__filter_property(delta.state)

        try:
            if value is None:
                logger.debug(
                    f"  Delta reports that '{self.label()}' was deleted. Resetting defaults..."
                )
                self.change_reported_value(SHADOW_VALUE_DEFAULT)
                return
            else:
                logger.debug(
                    f"  Delta reports that desired value is '{value}'. Invoke delta func..."
                )
                try:
                    self.delta_func(self.thing_name, self.label(), value)
                except ExceptionAwsIotShadowInvalidDelta:
                    logger.debug(
                        f"  Delta reports invalid request in {self.label()}. Resetting defaults..."
                    )
                    self.change_desired_value(SHADOW_VALUE_DEFAULT)
        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def on_get_shadow_accepted(self, response: iotshadow.GetShadowResponse) -> None:
        logger.debug("Finished getting initial shadow state.")
        if self.locked_data.get_reported_value() is not None:
            logger.debug(
                "  Ignoring initial query because a delta event has already been received."
            )
            return

        try:
            if response.state:
                if response.state.delta:
                    value = self.__filter_property(response.state.delta)
                    if value:
                        logger.debug(f"  Shadow contains delta value '{value}'.")
                        return

                if response.state.reported:
                    value = self.__filter_property(response.state.reported)
                    if value:
                        logger.debug(f"  Shadow contains reported value '{value}'.")
                        self.locked_data.set_reported_value(value)
                        return

            logger.debug(
                f"  Shadow document lacks '{self.label()}' property. Setting defaults..."
            )
            self.change_reported_value(SHADOW_VALUE_DEFAULT)

        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def on_get_shadow_rejected(self, error: iotshadow.ErrorResponse) -> None:
        if error.code == 404:
            logger.debug("Thing has no shadow document. Creating with defaults...")
            self.change_reported_value(SHADOW_VALUE_DEFAULT)
        else:
            raise ExceptionAwsIotClient(error)

    def on_update_shadow_accepted(
        self, response: iotshadow.UpdateShadowResponse
    ) -> None:
        try:
            if response.state.reported:
                logger.debug(
                    f"Finished updating reported shadow value to '{response.state.reported}'."
                )
            if response.state.desired:
                logger.debug(
                    f"Finished updating desired shadow value to '{response.state.desired}'."
                )
                self.locked_data.set_desired_value(response.state.desired)
                self.desired_func(self.thing_name, self.label(), response.state.desired)
        except Exception as e:
            logger.error(format_exc())
            logger.error("Updated shadow is missing the target property.")
            raise (e)

    def on_update_shadow_rejected(self, error: iotshadow.ErrorResponse) -> None:
        logger.error(
            f"Update request was rejected. code:{error.code} message:'{error.message}'"
        )
        raise ExceptionAwsIotClient(error)

    def on_publish_update_shadow(self, future: Future) -> None:
        try:
            future.result()
            logger.debug("Update request published.")
        except Exception as e:
            logger.error(format_exc())
            logger.debug("Failed to publish update request.")
            raise (e)

    @abstractmethod
    def update_shadow_request(
        self, desired: ShadowDocument, reported: ShadowDocument
    ) -> "Future[None]":
        pass

    def change_reported_value(self, value: ShadowDocument) -> "Future[None]":
        reported = self.locked_data.update_reported_value(value, self.publish_full_doc)

        logger.debug(f"Updating reported shadow value to '{reported}'...")
        return self.update_shadow_request(reported=reported, desired=None)

    def change_desired_value(self, value: ShadowDocument) -> "Future[None]":
        desired = self.locked_data.update_desired_value(value, self.publish_full_doc)

        logger.debug(f"Updating desired shadow value to '{desired}'...")
        return self.update_shadow_request(reported=None, desired=desired)

    def change_both_values(
        self, desired_value: ShadowDocument, reported_value: ShadowDocument
    ) -> "Future[None]":
        desired, reported = self.locked_data.update_both_values(
            desired_value, reported_value, self.publish_full_doc
        )

        return self.update_shadow_request(desired=desired, reported=reported)
