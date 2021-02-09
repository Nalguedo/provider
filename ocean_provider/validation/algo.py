import json

from eth_utils import add_0x_prefix
from ocean_provider.myapp import app
from ocean_provider.serializers import StageAlgoSerializer
from ocean_provider.util import (
    build_stage_dict,
    build_stage_output_dict,
    get_asset_download_urls,
    get_metadata_url,
)
from ocean_provider.utils.basics import get_asset_from_metadatastore
from ocean_utils.agreements.service_types import ServiceTypes
from ocean_utils.did import did_to_id


class AlgoValidator:
    def __init__(self, consumer_address, provider_wallet, data, service, asset):
        """Initializes the validator."""
        self.consumer_address = consumer_address
        self.provider_wallet = provider_wallet
        self.data = data
        self.service = service
        self.did = data.get("documentId")
        self.asset = asset

    def validate(self):
        """Validates for algo, input and output contents."""
        if not self.validate_algo():
            return False

        if not self.validate_input():
            return False

        if not self.validate_additional_input():
            return False

        if not self.validate_output():
            return False

        self.stage = build_stage_dict(
            self.validated_input_dict,
            self.validated_algo_dict,
            self.validated_output_dict,
        )

        return True

    def validate_input(self):
        """Validates input dictionary."""
        asset_urls = get_asset_download_urls(
            self.asset, self.provider_wallet, config_file=app.config["CONFIG_FILE"]
        )

        if not asset_urls:
            self.error = f"cannot get url(s) in input did {self.did}."
            return False

        self.validated_input_dict = dict(
            {"index": 0, "id": self.did, "url": asset_urls}
        )

        return True

    def validate_additional_input(self):
        """Validates additional input dictionary."""
        if not self.data.get("additionalInput"):
            return True

        self.additional_stages = []

        for index, input_item in enumerate(self.data["additionalInput"]):
            input_item_validator = InputItemValidator(
                self.consumer_address,
                self.provider_wallet,
                input_item,
                self.validated_algo_dict,
                self.validated_output_dict,
                index + 1,
            )
            status = input_item_validator.validate()
            if not status:
                self.error = (
                    f"Error in additionalInput at index {index}: "
                    + input_item_validator.error
                )
                return False

            self.additional_stages.append(status)

        return True

    def validate_output(self):
        """Validates output dictionary after stage build."""
        output_def = self.data.get("output", dict())

        if output_def and isinstance(output_def, str):
            output_def = json.loads(output_def)

        self.validated_output_dict = build_stage_output_dict(
            output_def, self.asset, self.consumer_address, self.provider_wallet
        )

        return True

    def _build_and_validate_algo(self, algo_data):
        """Returns False if invalid, otherwise sets the validated_algo_dict attribute."""
        algorithm_did = algo_data.get("algorithmDid")
        algo = get_asset_from_metadatastore(get_metadata_url(), algorithm_did)
        try:
            asset_type = algo.metadata["main"]["type"]
        except ValueError:
            asset_type = None

        if asset_type != "algorithm":
            self.error = f"DID {algorithm_did} is not a valid algorithm"
            return False

        algorithm_dict = StageAlgoSerializer(
            self.consumer_address, self.provider_wallet, algo_data
        ).serialize()

        valid, error_msg = validate_formatted_algorithm_dict(
            algorithm_dict, algorithm_did
        )

        if not valid:
            self.error = error_msg
            return False

        self.validated_algo_dict = algorithm_dict

        return True

    def validate_algo(self):
        """Validates algorithm details that allow the algo dict to be built."""
        algorithm_meta = self.data.get("algorithmMeta")
        algorithm_did = self.data.get("algorithmDid")
        algorithm_meta = self.data.get("algorithmMeta")

        privacy_options = self.service.main.get("privacy", {})

        if self.service is None:
            self.error = f"This DID has no compute service {self.did}."
            return False

        if algorithm_meta and privacy_options.get("allowRawAlgorithm", True) is False:
            self.error = f"cannot run raw algorithm on this did {self.did}."
            return False

        trusted_algorithms = privacy_options.get("trustedAlgorithms", [])

        if (
            algorithm_did
            and trusted_algorithms
            and algorithm_did not in trusted_algorithms
        ):
            self.error = f"cannot run raw algorithm on this did {self.did}."
            return False

        if algorithm_meta and isinstance(algorithm_meta, str):
            algorithm_meta = json.loads(algorithm_meta)

        return self._build_and_validate_algo(self.data)


def validate_formatted_algorithm_dict(algorithm_dict, algorithm_did):
    if algorithm_did and not (
        algorithm_dict.get("url") or algorithm_dict.get("remote")
    ):
        return False, f"cannot get url for the algorithmDid {algorithm_did}"

    if (
        not algorithm_dict.get("url")
        and not algorithm_dict.get("rawcode")
        and not algorithm_dict.get("remote")
    ):
        return (
            False,
            "algorithmMeta must define one of `url` or `rawcode` or `remote`, but all seem missing.",
        )  # noqa

    container = algorithm_dict["container"]
    # Validate `container` data
    if not (
        container.get("entrypoint") and container.get("image") and container.get("tag")
    ):
        return (
            False,
            "algorithm `container` must specify values for all of entrypoint, image and tag.",
        )  # noqa

    return True, ""


class InputItemValidator(AlgoValidator):
    def __init__(
        self,
        consumer_address,
        provider_wallet,
        data,
        parent_validated_algo_dict,
        parent_validated_output_dict,
        index,
    ):
        self.consumer_address = consumer_address
        self.provider_wallet = provider_wallet
        self.data = data
        self.parent_validated_algo_dict = parent_validated_algo_dict
        self.parent_validated_output_dict = parent_validated_output_dict
        self.index = index

    def validate(self):
        """Validates for input and output contents and inherits the rest."""
        if not self.validate_input():
            return False

        self.stage = build_stage_dict(
            self.validated_input_dict,
            self.parent_validated_algo_dict,
            self.parent_validated_output_dict,
            index=self.index,
        )

        return True

    def validate_input(self):
        required_keys = ["did", "transferTxId", "serviceId"]

        for req_item in required_keys:
            if not self.data.get("key"):
                self.error = f"No {req_item} in additionalInput."
                return False

        did = self.data.get("did")
        did = add_0x_prefix(did_to_id(did)) if did.startswith("did:") else did
        self.asset = get_asset_from_metadatastore(get_metadata_url(), did)

        if not self.asset:
            self.error = f"Asset for did {did} not found."
            return False

        self.service = self.asset.services[self.data["serviceId"]]

        if self.service.type not in [
            ServiceTypes.ASSET_ACCESS,
            ServiceTypes.CLOUD_COMPUTE,
        ]:
            self.error = "Services in additionalInput can only be access or compute."
            return False

        return super().validate_input()
