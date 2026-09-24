from abc import ABC, abstractmethod
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from traceback import format_exc
from typing import Any, Callable, Dict, Optional, Tuple

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


def deletion_patch(delta: Dict[str, Any]) -> Dict[str, Any]:
    """An update that deletes exactly the leaves listed in ``delta``."""
    return {
        k: deletion_patch(v) if isinstance(v, dict) and v else None
        for k, v in delta.items()
    }


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

    def merge(self, patch: Any) -> ShadowDocument:
        """Apply a partial update as the Device Shadow service does."""
        if isinstance(patch, dict) and (
            self._current is None or isinstance(self._current, dict)
        ):
            self._current = dictdiff.dictmerge(self._current, patch)
        else:
            self._current = deepcopy(patch)
        return deepcopy(self._current)


@dataclass
class ShadowData:
    _lock: Lock = field(default_factory=Lock)
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

    def merge_desired_value(self, patch: Any) -> ShadowDocument:
        with self._lock:
            return self._desired_value.merge(patch)

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
    locked_data: ShadowData
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
        self.locked_data = ShadowData()

    def __filter_property(self, v: ShadowDocument) -> ShadowDocument:
        if self.property_name is None or v is None:
            return v
        return v.get(self.property_name)

    def __wrap_property(self, v: ShadowDocument) -> ShadowDocument:
        if self.property_name is None or v is None:
            return v
        return {self.property_name: v}

    def label(self) -> str:
        return self.property_name or ""

    def on_shadow_delta_updated(self, delta: iotshadow.ShadowDeltaUpdatedEvent) -> None:
        logger.debug("Received shadow delta event.")
        value = self.__filter_property(delta.state) if delta.state else None
        if value is None or value == {}:
            # A delta lists every desired key that differs from reported, so on
            # a shared classic shadow it may only concern other properties. An
            # empty object is what deleting all of its keys may leave behind.
            logger.debug(f"  Delta did not report a change in '{self.label()}'")
            return

        self.__handle_delta(value)

    def __handle_delta(self, value: Dict[str, Any]) -> None:
        try:
            logger.debug(
                f"  Delta reports that desired value is '{value}'. Invoke delta func..."
            )
            try:
                self.delta_func(self.thing_name, self.label(), value)
            except ExceptionAwsIotShadowInvalidDelta:
                logger.debug(
                    f"  Delta reports invalid request in {self.label()}. Resetting defaults..."
                )
                self.__clear_desired(value)
        except Exception as e:
            logger.error(format_exc())
            raise (e)

    def __clear_desired(self, delta: Any) -> "Future[None]":
        # Deleting the rejected leaves removes the delta and keeps the rest of
        # the desired value. The local desired value follows through
        # on_update_shadow_accepted.
        patch = deletion_patch(delta) if isinstance(delta, dict) else None
        if self.property_name is not None:
            patch = {self.property_name: patch}
        return self._publish_update(desired=patch, reported=None)

    def on_get_shadow_accepted(self, response: iotshadow.GetShadowResponse) -> None:
        logger.debug("Finished getting initial shadow state.")
        try:
            state = response.state
            if state is None:
                state = iotshadow.ShadowStateWithDelta()

            # The response may arrive after the application already changed
            # values; those are newer than the response.
            if self.locked_data.get_desired_value() is None:
                self.locked_data.set_desired_value(
                    self.__filter_property(state.desired)
                )

            reported = self.__filter_property(state.reported)
            if self.locked_data.get_reported_value() is not None:
                logger.debug(
                    "  Keeping the reported value set before the initial query returned."
                )
            elif reported is not None:
                logger.debug(f"  Shadow contains reported value '{reported}'.")
                self.locked_data.set_reported_value(reported)
            else:
                logger.debug(
                    f"  Shadow document lacks '{self.label()}' property. Setting defaults..."
                )
                self.change_reported_value(SHADOW_VALUE_DEFAULT)

            delta = self.__filter_property(state.delta)
            if delta is not None and delta != {}:
                logger.debug(f"  Shadow contains delta value '{delta}'.")
                self.__handle_delta(delta)

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
            desired = response.state.desired
            if not desired:
                return
            if self.property_name is not None and self.property_name not in desired:
                return  # Update of another property on a shared classic shadow

            # The response only echoes the request, which may be a difference.
            value = self.locked_data.merge_desired_value(
                self.__filter_property(desired)
            )
            logger.debug(f"Finished updating desired shadow value to '{value}'.")
            self.desired_func(self.thing_name, self.label(), value)
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
    def _publish_update(
        self, desired: ShadowDocument, reported: ShadowDocument
    ) -> "Future[None]":
        """Publish an update request whose state sections are already complete."""

    def update_shadow_request(
        self, desired: ShadowDocument, reported: ShadowDocument
    ) -> "Future[None]":
        if desired is None and reported is None:
            return done_future()

        return self._publish_update(
            desired=self.__wrap_property(desired),
            reported=self.__wrap_property(reported),
        )

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
