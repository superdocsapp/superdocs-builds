import { useEffect, useState } from "react";
import axios from "axios";

const API = "http://127.0.0.1:8000";

function App() {
  const [form, setForm] = useState({
    name: "",
    license: "MIT",
    governance_model: "Maintainer-led",
    contact_email: "",
  });

  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [generatedDocuments, setGeneratedDocuments] = useState([]);
  const [generatingProjectId, setGeneratingProjectId] = useState(null);
const [downloadingProjectId, setDownloadingProjectId] = useState(null);
const [deletingProjectId, setDeletingProjectId] = useState(null);


  // -----------------------------
  // Get Projects From Backend
  // -----------------------------
  const fetchProjects = async () => {
    try {
      setLoadingProjects(true);

      const response = await axios.get(`${API}/api/projects`);

      setProjects(response.data);
    } catch (error) {
      console.error(error);
      setError("Unable to load projects.");
    } finally {
      setLoadingProjects(false);
    }
  };

  // -----------------------------
  // Load projects when page opens
  // -----------------------------
  useEffect(() => {
    fetchProjects();
  }, []);

  // -----------------------------
  // Form input handler
  // -----------------------------
  const handleChange = (event) => {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));
  };

  // -----------------------------
  // Create Project
  // -----------------------------
  const handleSubmit = async (event) => {
  event.preventDefault();

  const projectName = form.name.trim();
  const email = form.contact_email.trim();

  if (projectName.length < 3) {
    setError("Project name must be at least 3 characters.");
    return;
  }

  if (!email) {
    setError("Contact email is required.");
    return;
  }

  setLoading(true);
  setMessage("");
  setError("");


    try {
      const response = await axios.post(
        `${API}/api/projects`,
        form
      );

      setMessage(
        `Project "${response.data.name}" created successfully.`
      );

      // Clear form
      setForm({
        name: "",
        license: "MIT",
        governance_model: "Maintainer-led",
        contact_email: "",
      });

      // Refresh project list
      fetchProjects();

    } catch (error) {
      console.error(error);

      if (error.response?.data?.detail) {
        setError(
          JSON.stringify(error.response.data.detail)
        );
      } else {
        setError("Unable to create project.");
      }
    } finally {
      setLoading(false);
    }
  };
// -----------------------------
// Generate Project Documents
// -----------------------------
const handleGenerate = async (projectId) => {
  setMessage("");
  setError("");
  setGeneratingProjectId(projectId);

  try {
    const response = await axios.post(
      `${API}/api/projects/${projectId}/generate`
    );

    setGeneratedDocuments(response.data.documents);

    setMessage(
      `Documents generated successfully for "${response.data.project_name}".`
    );

  } catch (error) {
  console.error(error);

  const status = error.response?.status;
  const detail = error.response?.data?.detail;

  if (status === 409) {
    setError("A project with this name already exists.");
  } else if (status === 422) {
    if (Array.isArray(detail)) {
      setError(
        detail
          .map((item) => item.msg)
          .join(", ")
      );
    } else {
      setError("Please check your project details.");
    }
  } else if (status === 500) {
    setError("Server error. Please try again later.");
  } else {
    setError("Unable to create project.");
  }
} finally {
    setGeneratingProjectId(null);
  }
};
// -----------------------------
// Download Generated Document
// -----------------------------
const handleDownload = (doc) => {
  const blob = new Blob(
    [doc.content],
    { type: "text/markdown;charset=utf-8" }
  );

  const url = URL.createObjectURL(blob);

  const link = window.document.createElement("a");

  link.href = url;
  link.download = doc.filename;

  window.document.body.appendChild(link);

  link.click();

  window.document.body.removeChild(link);

  URL.revokeObjectURL(url);
};
// -----------------------------
// Delete Project
// -----------------------------
const handleDelete = async (projectId) => {
  const confirmed = window.confirm(
    "Are you sure you want to delete this project?"
  );

  if (!confirmed) {
    return;
  }

  setMessage("");
  setError("");
  setDeletingProjectId(projectId);

  try {
    await axios.delete(
      `${API}/api/projects/${projectId}`
    );

    setMessage("Project deleted successfully.");

    // Refresh project list
    fetchProjects();

    // Clear generated documents
    setGeneratedDocuments([]);

  } catch (error) {
    console.error(error);

    if (error.response?.data?.detail) {
      setError(
        JSON.stringify(error.response.data.detail)
      );
    } else {
      setError("Unable to delete project.");
    }
  }
};
// -----------------------------
// Download All Documents as ZIP
// -----------------------------
const handleDownloadAll = async (projectId) => {
  setMessage("");
  setError("");
  setDownloadingProjectId(projectId);

  try {
    const response = await axios.get(
      `${API}/api/projects/${projectId}/download`,
      {
        responseType: "blob",
      }
    );

    const url = window.URL.createObjectURL(
      new Blob([response.data])
    );

    const link = document.createElement("a");

    link.href = url;

    link.setAttribute(
      "download",
      `project-${projectId}-governance-pack.zip`
    );

    document.body.appendChild(link);

    link.click();

    link.remove();

    window.URL.revokeObjectURL(url);

    setMessage("Governance pack downloaded successfully.");

  } catch (error) {
    console.error(error);

    setError("Unable to download documents.");

  } finally {
    setDownloadingProjectId(null);
  }
};

  return (
    <main className="page">
      <section className="container">

        {/* Header */}
        <div className="header">
          <div className="eyebrow">
            DOCTASK
          </div>

          <h1>
            Open-source Governance Pack
          </h1>

          <p>
            Create and manage governance projects
            from one place.
          </p>
        </div>

        {/* Create Project */}
        <div className="card">

          <h2>Create Project</h2>

          <form onSubmit={handleSubmit}>

            <label>
              Project Name

              <input
                type="text"
                name="name"
                value={form.name}
                onChange={handleChange}
                placeholder="e.g. AI Notes"
                required
              />
            </label>

            <label>
              License

              <select
                name="license"
                value={form.license}
                onChange={handleChange}
              >
                <option value="MIT">MIT</option>
                <option value="Apache-2.0">
                  Apache-2.0
                </option>
                <option value="GPL-3.0">
                  GPL-3.0
                </option>
                <option value="BSD-3-Clause">
                  BSD-3-Clause
                </option>
              </select>
            </label>

            <label>
              Governance Model

              <select
                name="governance_model"
                value={form.governance_model}
                onChange={handleChange}
              >
                <option value="Maintainer-led">
                  Maintainer-led
                </option>

                <option value="BDFL">
                  BDFL
                </option>

                <option value="Community-elected">
                  Community-elected
                </option>

                <option value="Foundation-governed">
                  Foundation-governed
                </option>
              </select>
            </label>

            <label>
              Contact Email

              <input
                type="email"
                name="contact_email"
                value={form.contact_email}
                onChange={handleChange}
                placeholder="security@example.com"
                required
              />
            </label>

            <button
              type="submit"
              disabled={loading}
            >
              {loading
                ? "Creating..."
                : "Create Project"}
            </button>

          </form>

          {message && (
            <div className="success">
              {message}
            </div>
          )}

          {error && (
            <div className="error">
              {error}
            </div>
          )}

        </div>

        {/* Project List */}
        <div className="card">

          <div className="projects-header">
            <div>
              <h2>Your Projects</h2>

              <p>
                Projects saved in your database.
              </p>
            </div>

            <button
              className="refresh"
              onClick={fetchProjects}
            >
              Refresh
            </button>
          </div>

          {loadingProjects ? (
            <p>Loading projects...</p>
          ) : projects.length === 0 ? (
            <div className="empty">
              No projects found.
            </div>
          ) : (
            <div className="project-list">

              {projects.map((project) => (
                <div
                  className="project-item"
                  key={project.id}
                >

                  <div>
                    <h3>
                      {project.name}
                    </h3>

                    <p>
                      {project.contact_email}
                    </p>
                  </div>

                  <div className="badges">

                    <span>
                      {project.license}
                    </span>

                    <span>
                      {project.governance_model}
                    </span>

                  </div>
                  <button
  className="generate-button"
  onClick={() => handleGenerate(project.id)}
  disabled={generatingProjectId === project.id}
>
  {generatingProjectId === project.id
    ? "Generating..."
    : "Generate Documents"}
</button>


<button
  className="delete-button"
  onClick={() => handleDelete(project.id)}
>
  Delete
</button>

<button
  className="download-all-button"
  onClick={() => handleDownloadAll(project.id)}
  disabled={downloadingProjectId === project.id}
>
  {downloadingProjectId === project.id
    ? "Downloading..."
    : "Download All as ZIP"}
</button>

                </div>
              ))}

            </div>
          )}

        </div>
         {/* Generated Documents */}
    {generatedDocuments.length > 0 && (
      <div className="card">

        <h2>Generated Documents</h2>

        <p>
          Documents generated from your project templates.
        </p>

        <div className="document-list">

          {generatedDocuments.map((document) => (
            <div
              className="document-item"
              key={document.filename}
            >

              <h3>
                {document.filename}
              </h3>
              <button
  className="download-button"
  onClick={() => handleDownload(document)}
>
  Download
</button>
              <pre>
                {document.content}
              </pre>

            </div>
          ))}

        </div>

      </div>
    )}

      </section>
    </main>
  );
}

export default App;