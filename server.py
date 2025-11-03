import subprocess
import os
import random
import shutil
import http.server
import socketserver
import json
import threading

# --- Slug Generation (Same as before) ---
ADJECTIVES = [
    "lazy", "great", "blue", "fast", "bright", "sharp", "wise", "dark",
    "silent", "empty", "clever", "jolly", "brave", "calm", "eager"
]
NOUNS = [
    "scientist", "ocean", "river", "fox", "tree", "sky", "mountain", "bear",
    "comet", "star", "moon", "sun", "robot", "cat", "dog"
]

def generate_slug():
    """Generates a random adjective-adjective-noun slug."""
    adj1 = random.choice(ADJECTIVES)
    adj2 = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    while adj1 == adj2:
        adj2 = random.choice(ADJECTIVES)
    return f"{adj1}-{adj2}-{noun}"
# --- End Slug Generation ---

# --- Global state ---
deployed_sites = {}
deploy_lock = threading.Lock()

# --- NEW: Define paths ---
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
# Temp directory for cloning
CLONE_PARENT_DIR = os.path.join(ROOT_DIR, "cloned_sites_temp")
# NEW: Permanent directory for built sites
DEPLOYMENTS_DIR = os.path.join(ROOT_DIR, "deployments")

# Create directories
os.makedirs(CLONE_PARENT_DIR, exist_ok=True)
os.makedirs(DEPLOYMENTS_DIR, exist_ok=True)

# --- NEW: Define base hostnames ---
# The server will serve the main index.html from these hostnames
PORT = 8000
BASE_HOSTNAMES = [
    f"localhost",
    f"127.0.0.1",
    f"deployer.com" # For if you set this in your hosts file
]


def deploy_frontend(repo_url, base_path):
    """
    Clones, builds, copies to deployments, and cleans up.
    Returns the slug if successful, None otherwise.
    """
    slug = generate_slug()
    print(f"[{slug}] Deployment started for {repo_url}")
    
    clone_dir = os.path.join(CLONE_PARENT_DIR, slug)
    # NEW: Final destination for build files
    target_deploy_dir = os.path.join(DEPLOYMENTS_DIR, slug)
    
    try:
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        if not repo_name:
            raise ValueError("Could not determine repository name from URL.")
    except Exception as e:
        print(f"[{slug}] Error: Invalid GitHub URL. {e}")
        return None
        
    try:
        # --- 1. Clean & Clone ---
        if os.path.exists(clone_dir):
            print(f"[{slug}] Removing existing temp directory: {clone_dir}")
            shutil.rmtree(clone_dir)
            
        print(f"[{slug}] Cloning {repo_url} into {clone_dir}...")
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, clone_dir], 
            check=True, capture_output=True, text=True
        )
        print(f"[{slug}] Clone successful.")

        # --- 2. Build Project ---
        print(f"[{slug}] Running 'npm install && npm run build'...")
        build_command = "npm install && npm run build"
        subprocess.run(
            build_command, 
            shell=True, 
            cwd=clone_dir, 
            check=True,
            capture_output=True, text=True
        )
        print(f"[{slug}] Build successful.")

        # --- 3. Find Build Directory ---
        build_dir = os.path.abspath(os.path.join(clone_dir, "dist"))
        
        if not os.path.isdir(build_dir):
            print(f"[{slug}] Error: Specified base path '{"dist"}' not found after build.")
            print(f"[{slug}] Looked for: {build_dir}")
            raise FileNotFoundError(f"Build directory '{"dist"}' not found.")

        print(f"[{slug}] Found build directory: {build_dir}")

        # --- 4. NEW: Copy to deployments folder ---
        if os.path.exists(target_deploy_dir):
            shutil.rmtree(target_deploy_dir)
        
        print(f"[{slug}] Copying from {build_dir} to {target_deploy_dir}")
        shutil.copytree(build_dir, target_deploy_dir)
        print(f"[{slug}] Copy complete.")

        # --- 5. Register (Thread-safe) ---
        with deploy_lock:
            deployed_sites[slug] = target_deploy_dir
        
        print(f"[{slug}] Deployment complete. Site active at http://{slug}.localhost:{PORT}/")
        return slug

    except subprocess.CalledProcessError as e:
        print(f"\n[{slug}] Error: Process failed. {e.stderr}")
        return None
    except Exception as e:
        print(f"[{slug}] An unexpected error occurred: {e}")
        return None
    finally:
        # --- 6. NEW: Clean up clone directory ---
        if os.path.exists(clone_dir):
            print(f"[{slug}] Cleaning up temp clone directory: {clone_dir}")
            shutil.rmtree(clone_dir)
            print(f"[{slug}] Cleanup complete.")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in a separate thread."""
    pass

class DeployServerHandler(http.server.SimpleHTTPRequestHandler):
    
    def __init__(self, *args, **kwargs):
        """
        Set the directory to ROOT_DIR initially to serve the main index.html.
        This is crucial for translate_path to work correctly.
        """
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def do_GET(self):
        """NEW: Serve based on Host header."""
        
        # Get hostname, strip port
        host_header = self.headers.get('Host', '').split(':')[0]
        
        # Check if it's a request for the main deployer page
        if host_header in BASE_HOSTNAMES:
            # Serve the main index.html
            self.directory = ROOT_DIR
            if self.path == '/':
                self.path = '/index.html'
            return super().do_GET()

        # Otherwise, assume it's a request for a deployed site
        slug = host_header.split('.')[0]
        
        with deploy_lock:
            site_dir = deployed_sites.get(slug)
        
        if site_dir:
            # Found a deployed site, serve its files
            self.directory = site_dir
            
            # If no file is specified, serve index.html from that dir
            # This is critical for React/Vue routers to work
            filepath = os.path.join(self.directory, self.path.lstrip('/'))
            if os.path.isdir(filepath) or not os.path.exists(filepath):
                 self.path = '/index.html'
            
            return super().do_GET()
        else:
            # No site found
            self.send_error(404, f"Site not found. No deployment registered for '{slug}'.")

    def do_POST(self):
        """Handle deployment requests (mostly unchanged)."""
        if self.path == '/api/deploy':
            try:
                content_length = int(self.headers['Content-Length'])
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
                
                repo_url = data.get('url')
                base_path = data.get('base_path')
                
                if not repo_url or not base_path:
                    self.send_error(400, "Missing 'url' or 'base_path'")
                    return

                slug = deploy_frontend(repo_url, base_path)
                
                if slug:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    # NEW: Return the full subdomain URL
                    response = {
                        "slug": slug,
                        "url": f"http://{slug}.localhost:{PORT}/"
                    }
                    self.wfile.write(json.dumps(response).encode('utf-8'))
                else:
                    self.send_error(500, "Deployment failed. Check server logs.")
                    
            except Exception as e:
                print(f"Error during POST: {e}")
                self.send_error(500, f"Server error: {e}")
        else:
            self.send_error(404, "Not Found")

if __name__ == "__main__":
    print(f"--- Mini Deployer Server ---")
    print(f"Serving main app on: http://localhost:{PORT}")
    print(f"Deployed sites will be served on: http://<slug>.localhost:{PORT}")
    print(f"\nBuilt sites stored in: {DEPLOYMENTS_DIR}")
    print(f"Temp clones in: {CLONE_PARENT_DIR}")
    print("\nIMPORTANT: You must edit your 'hosts' file to access deployed sites.")
    print("Example: Add '127.0.0.1 my-new-site.localhost' to your hosts file.")
    print("\nPress Ctrl+C to stop.")
    
    httpd = ThreadedHTTPServer(("", PORT), DeployServerHandler)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        httpd.server_close()