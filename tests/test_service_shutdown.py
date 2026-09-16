from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

import hub
import server


class ServiceShutdownTests(unittest.TestCase):
    def assert_shutdown_endpoint(self, handler: type, path: str, token: str) -> None:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        serving = threading.Thread(target=httpd.serve_forever, daemon=True)
        serving.start()
        connection: http.client.HTTPConnection | None = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            connection.request("POST", path, headers={"X-Requirement-Flow-Token": "invalid-token"})
            denied = connection.getresponse()
            denied.read()
            self.assertEqual(denied.status, 403)
            self.assertTrue(serving.is_alive())
            connection.close()

            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            connection.request("POST", path, headers={"X-Requirement-Flow-Token": token})
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(payload, {"ok": True, "stopping": True})
            serving.join(timeout=2)
            self.assertFalse(serving.is_alive())
        finally:
            if connection is not None:
                connection.close()
            if serving.is_alive():
                httpd.shutdown()
            httpd.server_close()
            serving.join(timeout=2)

    def test_hub_shutdown_endpoint_stops_server(self) -> None:
        self.assert_shutdown_endpoint(hub.HubHandler, "/api/hub/shutdown", hub.HUB_TOKEN)

    def test_controller_shutdown_endpoint_stops_server(self) -> None:
        self.assert_shutdown_endpoint(server.WorkflowHandler, "/api/shutdown", server.SESSION_TOKEN)


if __name__ == "__main__":
    unittest.main()
