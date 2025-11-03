const form = document.getElementById("deploy-form");
const button = document.getElementById("deploy-button");
const loading = document.getElementById("loading");
const result = document.getElementById("result");
const repoUrlInput = document.getElementById("repo-url");
const basePathInput = document.getElementById("base-path");

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const url = repoUrlInput.value;
  const base_path = basePathInput.value ? basePathInput.value : "/";

  // Disable form and show loading
  button.disabled = true;
  button.textContent = "Deploying...";
  loading.style.display = "block";
  result.style.display = "none";
  result.innerHTML = "";
  result.className = "";

  try {
    const response = await fetch("/api/deploy", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url, base_path }),
    });

    if (response.ok) {
      const data = await response.json();
      result.className = "success";
      result.innerHTML = `
                        <strong>Success!</strong>
                        <p>Site ID: <strong>${data.slug}</strong></p>
                        <a href="${data.url}" target="_blank" id="result-url">
                            Go to Site
                        </a>
                    `;
    } else {
      const errorText = (await response.text()) || "Deployment failed.";
      throw new Error(`Server error: ${response.status} ${errorText}`);
    }
  } catch (err) {
    result.className = "error";
    result.innerHTML = `<strong>Error:</strong> ${err.message}`;
    console.error(err);
  } finally {
    // Re-enable form
    button.disabled = false;
    button.textContent = "Deploy";
    loading.style.display = "none";
    result.style.display = "block";
  }
});
