import os
import sys
import unittest

import httpx


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)

from app.services.dongmac_client import (  # noqa: E402
    DongMacApiError,
    DongMacClient,
    DongMacCredentials,
    build_trigger_payload,
)


class DongMacClientTests(unittest.TestCase):
    def test_builds_minimal_trigger_payload(self):
        payload = build_trigger_payload(template_id=12, operator="tester")

        self.assertEqual(payload["templateId"], 12)
        self.assertEqual(payload["operator"], "tester")
        self.assertNotIn("deviceStrategy", payload)
        self.assertNotIn("callbackConfigs", payload)
        self.assertNotIn("repoConfig", payload)

    def test_builds_optional_device_callback_and_extra_params(self):
        payload = build_trigger_payload(
            template_id=12,
            operator="tester",
            device_serial="device-1",
            callback_url="https://internal.example/callback",
            callback_token="callback-secret",
            instruction_ids=[2049],
            extra_params={"targetUrl": "https://example.com", "instruction": "打开页面并截图"},
        )

        self.assertEqual(payload["deviceStrategy"]["specifyDevices"], ["device-1"])
        self.assertEqual(payload["repoConfig"]["extraParams"]["targetUrl"], "https://example.com")
        self.assertEqual(payload["caseConfig"]["uiGenieCase"]["instructionIds"], [2049])
        callback = payload["callbackConfigs"][0]
        self.assertTrue(callback["enabled"])
        self.assertEqual(callback["headers"]["X-DongMAC-Callback-Token"], "callback-secret")

    def test_authenticates_then_triggers_task(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/v1/auth/access-token":
                return httpx.Response(200, json={
                    "code": 2000,
                    "message": "操作成功",
                    "data": {"accessToken": "temporary-token", "expireInSeconds": 3600},
                    "success": True,
                })
            self.assertEqual(request.headers["accesstoken"], "temporary-token")
            return httpx.Response(200, json={
                "code": 2000,
                "message": "操作成功",
                "data": 35,
                "success": True,
            })

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        client = DongMacClient("http://dongmac.test", client=http_client)
        token = client.get_access_token(DongMacCredentials("business", "workspace-secret"))
        task_record_id = client.trigger_task(token, build_trigger_payload(template_id=1, operator="tester"))

        self.assertEqual(task_record_id, 35)
        self.assertEqual([request.url.path for request in requests], [
            "/api/v1/auth/access-token",
            "/api/v1/task/ci/trigger",
        ])
        http_client.close()

    def test_rejects_api_error_envelope(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            "code": 9999,
            "message": "workspaceToken invalid",
            "data": None,
            "success": False,
        }))
        http_client = httpx.Client(transport=transport)
        client = DongMacClient("http://dongmac.test", client=http_client)

        with self.assertRaisesRegex(DongMacApiError, "workspaceToken invalid"):
            client.get_access_token(DongMacCredentials("business", "bad-token"))

        http_client.close()


if __name__ == "__main__":
    unittest.main()
