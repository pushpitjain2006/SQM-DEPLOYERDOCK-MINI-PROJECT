import unittest
import unittest.mock
import threading
import time
import requests
import json
import os
import shutil

# --- Import the script to be tested ---
import server

# --- Define a predictable port ---
# Use the same port as the main script
PORT = server.PORT
BASE_URL = f"http://localhost:{PORT}"

class TestDeployServer(unittest.TestCase):
    """
    Integration test for the DeployServer.
    It runs the actual server in a thread and mocks out the slow
    deployment process (git clone, npm build).
    """

    httpd = None
    server_thread = None

    @classmethod
    def setUpClass(cls):
        """
        Set up the server and test environment.
        This runs ONCE before all tests.
        """
        # 1. Create a dummy index.html for the main server to serve
        # REMOVED: This was deleting your real index.html!
        # with open("index.html", "w") as f:
        #    f.write("This is the main server index page.")

        # 2. Set up and start the HTTP server in a background thread
        cls.httpd = server.ThreadedHTTPServer(("", PORT), server.DeployServerHandler)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever)
        cls.server_thread.daemon = True  # So it exits when the main thread exits
        cls.server_thread.start()
        
        # Give the server a moment to start up
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        """
        Stop the server and clean up.
        This runs ONCE after all tests.
        """
        # 1. Shut down the server
        if cls.httpd:
            cls.httpd.shutdown()
        if cls.server_thread:
            cls.server_thread.join()
            
        # 2. Clean up dummy files and directories
        # REMOVED: This was deleting your real index.html!
        # if os.path.exists("index.html"):
        #    os.remove("index.html")
        
        # Clean up directories created by the script
        if os.path.exists(server.CLONE_PARENT_DIR):
            shutil.rmtree(server.CLONE_PARENT_DIR, ignore_errors=True)
        if os.path.exists(server.DEPLOYMENTS_DIR):
            shutil.rmtree(server.DEPLOYMENTS_DIR, ignore_errors=True)

    def setUp(self):
        """
        This runs BEFORE EACH individual test.
        """
        # Clear the deployed_sites dictionary to ensure tests are isolated
        with server.deploy_lock:
            server.deployed_sites.clear()
            
        # Ensure the deployments directory exists and is empty
        if os.path.exists(server.DEPLOYMENTS_DIR):
            shutil.rmtree(server.DEPLOYMENTS_DIR)
        os.makedirs(server.DEPLOYMENTS_DIR)

    def tearDown(self):
        """
        This runs AFTER EACH individual test.
        (We do our main cleanup in setUp for a fresh start)
        """
        pass

    # --- The Mock Deployment Function ---
    
    def mock_deploy_frontend(self, repo_url, base_path):
        """
        This function REPLACES the real `deploy_frontend`.
        It fakes a successful deployment.
        """
        print("[TEST] MOCK deploy_frontend called")
        slug = "mock-test-site"
        
        # 1. Create the fake deployment directory
        target_dir = os.path.join(server.DEPLOYMENTS_DIR, slug)
        os.makedirs(target_dir, exist_ok=True)
        
        # 2. Create a fake index.html inside it
        with open(os.path.join(target_dir, "index.html"), "w") as f:
            f.write(f"Hello from the MOCK deployed site: {slug}")
            
        # 3. Register it with the *real* server's global state
        with server.deploy_lock:
            server.deployed_sites[slug] = target_dir
            
        # 4. Return the slug, just like the real function
        return slug

    def mock_deploy_frontend_fails(self, repo_url, base_path):
        """
        A mock function that fakes a FAILED deployment.
        """
        print("[TEST] MOCK deploy_frontend (FAILS) called")
        return None

    # --- The Tests ---

    def test_01_main_page_serves_ok(self):
        """Test that the main page (localhost) serves."""
        headers = {"Host": f"localhost:{PORT}"}
        response = requests.get(BASE_URL, headers=headers)
        
        self.assertEqual(response.status_code, 200)
        # We'll just check that the page loaded, not for specific content,
        # since it's your real file.
        self.assertGreater(len(response.text), 0)

    def test_02_post_deploy_success(self):
        """
        Test the entire /api/deploy flow with a mocked success.
        """
        # Use unittest.mock.patch to replace 'server.deploy_frontend'
        # with our 'mock_deploy_frontend' function *just for this block*.
        with unittest.mock.patch('server.deploy_frontend', new=self.mock_deploy_frontend):
            
            # 1. Make the POST request to trigger the deployment
            post_data = {
                "url": "https://github.com/fake/repo.git",
                "base_path": "dist"
            }
            response = requests.post(f"{BASE_URL}/api/deploy", json=post_data)
            
            # 2. Check the API response
            self.assertEqual(response.status_code, 200)
            response_json = response.json()
            self.assertEqual(response_json["slug"], "mock-test-site")
            self.assertEqual(response_json["url"], f"http://mock-test-site.localhost:{PORT}/")

            # 3. Check that the server state was updated
            self.assertIn("mock-test-site", server.deployed_sites)
            
            # 4. NOW, try to GET the newly "deployed" site.
            # This is the magic: we set the 'Host' header to trick
            # the server into thinking we're on a subdomain.
            site_headers = {"Host": f"mock-test-site.localhost:{PORT}"}
            site_response = requests.get(BASE_URL, headers=site_headers)
            
            self.assertEqual(site_response.status_code, 200)
            self.assertIn("Hello from the MOCK deployed site", site_response.text)

    def test_03_get_non_existent_site(self):
        """Test that requesting a slug that isn't deployed gives a 404."""
        headers = {"Host": f"not-a-real-site.localhost:{PORT}"}
        response = requests.get(BASE_URL, headers=headers)
        
        self.assertEqual(response.status_code, 404)

    def test_04_post_deploy_bad_data(self):
        """Test that the API returns 400 if data is missing."""
        post_data = {"url": "https://github.com/fake/repo.git"} # Missing base_path
        response = requests.post(f"{BASE_URL}/api/deploy", json=post_data)
        
        self.assertEqual(response.status_code, 400)

    def test_05_post_deploy_internal_failure(self):
        """Test that the API returns 500 if the (mock) deploy function fails."""
        
        # Patch server_frontend with the one that returns None
        with unittest.mock.patch('server.deploy_frontend', new=self.mock_deploy_frontend_fails):
            
            post_data = {
                "url": "https://github.com/fake/repo.git",
                "base_path": "dist"
            }
            response = requests.post(f"{BASE_URL}/api/deploy", json=post_data)
            
            # The server should report an internal error
            self.assertEqual(response.status_code, 500)

if __name__ == "__main__":
    unittest.main()

