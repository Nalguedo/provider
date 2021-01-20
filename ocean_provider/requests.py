from eth_utils import add_0x_prefix
from flask import request as flask_request
from flask_sieve import JsonRequest
from flask_sieve.rules_processor import RulesProcessor
from flask_sieve.validator import Validator
from ocean_utils.did import did_to_id

from ocean_provider.access_token import AccessToken
from ocean_provider.exceptions import InvalidSignatureError
from ocean_provider.user_nonce import UserNonce
from ocean_provider.util import get_request_data
from ocean_provider.utils.accounts import verify_signature
from ocean_provider.utils.basics import get_config

user_nonce = UserNonce(get_config().storage_path)
user_access_token = AccessToken(get_config().storage_path)


class CustomJsonRequest(JsonRequest):
    def __init__(self, request=None):
        request = request or flask_request
        request = get_request_data(request)
        self._validator = CustomValidator(rules=self.rules(), messages={
            'signature.signature': 'Invalid signature provided.',
            'transferTxId.access_token': 'There is already a token with these parameters'  # noqa
        }, request=request)


class CustomValidator(Validator):
    def __init__(
        self, rules=None, request=None, custom_handlers=None, messages=None,
        **kwargs
    ):
        super(CustomValidator, self).__init__(
            rules, request, custom_handlers, messages, **kwargs
        )
        self._processor = CustomRulesProcessor()


class CustomRulesProcessor(RulesProcessor):
    def validate_signature(self, value, params, **kwargs):
        self._assert_params_size(size=3, params=params, rule='signature')
        owner = self._attribute_value(params[0])
        did = self._attribute_value(params[1])
        rule = params[2]
        original_msg = f'{owner}{did}' if rule == 'customer_did' else f'{did}'
        try:
            verify_signature(
                owner, value, original_msg, user_nonce.get_nonce(owner)
            )
            return True
        except InvalidSignatureError:
            return False

        return False

    def validate_access_token(self, value, params, **kwargs):
        self._assert_params_size(size=2, params=params, rule='access_token')
        did = self._attribute_value(params[0])
        if did.startswith('did:'):
            did = add_0x_prefix(did_to_id(did))

        consumer_address = self._attribute_value(params[1])
        tx_id = value

        return user_access_token.check_unique(did, consumer_address, tx_id)


class NonceRequest(CustomJsonRequest):
    def rules(self):
        return {
            'userAddress': ['required'],
        }


class SimpleFlowConsumeRequest(CustomJsonRequest):
    def rules(self):
        return {
            'consumerAddress': ['required'],
            'dataToken': ['required'],
            'transferTxId': ['required']
        }


class EncryptRequest(CustomJsonRequest):
    def rules(self):
        return {
            'documentId': ['required'],
            'document': ['required'],
            'publisherAddress': ['required']
        }


class FileInfoRequest(CustomJsonRequest):
    def rules(self):
        return {
            'url': ['required_without:did'],
            'did': ['required_without:url', 'regex:^did:op']
        }


class ComputeRequest(CustomJsonRequest):
    def rules(self):
        return {
            'consumerAddress': ['required'],
            'signature': [
                'required',
                'signature:consumerAddress,documentId,only_did'
            ]
        }


class ComputeStartRequest(CustomJsonRequest):
    def rules(self):
        return {
            'documentId': ['required'],
            'serviceId': ['required'],
            'serviceType': ['required'],
            'dataToken': ['required'],
            'consumerAddress': ['required'],
            'transferTxId': ['required'],
            'output': ['required'],
            'algorithmMeta': ['required_without:algorithmDid'],
            'algorithmDid': [
                'required_without:algorithmMeta',
                'required_with_all:algorithmDataToken,algorithmTransferTxId'
            ],
            'signature': [
                'required',
                'signature:consumerAddress,documentId,customer_did'
            ],
        }


class AccessTokenRequest(CustomJsonRequest):
    def rules(self):
        return {
            'documentId': ['required'],
            'serviceId': ['required'],
            'serviceType': ['required'],
            'dataToken': ['required'],
            'consumerAddress': ['required'],
            'secondsToExpiration': ['required', 'integer'],
            'transferTxId': [
                'required',
                'access_token:documentId,consumerAddress'
            ],
            'fileIndex': ['required'],
            'signature': [
                'required',
                'signature:consumerAddress,documentId,only_did'
            ],
        }


class DownloadRequest(CustomJsonRequest):
    def rules(self):
        return {
            'documentId': ['required'],
            'serviceId': ['required'],
            'serviceType': ['required'],
            'dataToken': ['required'],
            'consumerAddress': ['required'],
            'transferTxId': ['required'],
            'fileIndex': ['required'],
            'signature': [
                'required',
                'signature:consumerAddress,documentId,only_did'
            ],
        }


class InitializeRequest(CustomJsonRequest):
    def rules(self):
        return {
            'documentId': ['required'],
            'serviceId': ['required'],
            'serviceType': ['required'],
            'dataToken': ['required'],
            'consumerAddress': ['required'],
        }