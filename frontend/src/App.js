import { useState, useEffect, useRef } from "react";
import "./App.css";

function App() {
  const [session, setSession] = useState("Research Session");
  const [sessions, setSessions] = useState([]);
  const [newSessionName, setNewSessionName] = useState("");
  const [isSessionsOpen, setIsSessionsOpen] = useState(true);
  const [pdfs, setPdfs] = useState([]);
  const [selectedPdfs, setSelectedPdfs] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);

  // Initial load
  useEffect(() => {
    loadSessions();
  }, []);

  // Auto-load PDFs when session changes
  useEffect(() => {
    if (session) {
      loadPdfs();
      setMessages([]); // Reset chat for new session
    }
  }, [session]);

  // Scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const loadSessions = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/sessions/");
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch (err) {
      console.error("Failed to load sessions", err);
    }
  };

  const loadPdfs = async () => {
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/pdfs/?session=${encodeURIComponent(session)}`
      );
      if (res.ok) {
        const data = await res.json();
        setPdfs(data.pdfs || []);
      }
    } catch (err) {
      console.error("Failed to load PDFs", err);
    }
  };

  const handleCreateSession = async (e) => {
    e?.preventDefault();
    if (!newSessionName.trim()) return;

    setStatus("Creating session...");
    try {
      const res = await fetch("http://127.0.0.1:8000/api/session/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newSessionName }),
      });
      if (res.ok) {
        setSession(newSessionName);
        setNewSessionName("");
        await loadSessions();
        setStatus("Session ready");
      }
    } catch (err) {
      setStatus("Error creating session");
    }
  };

  const deleteSession = async (e, name) => {
    e.stopPropagation();
    if (!window.confirm(`Delete entire workflow for "${name}"? This cannot be undone.`)) return;

    setStatus("Deleting session data...");
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/session/${encodeURIComponent(name)}/`, {
        method: "DELETE",
      });
      if (res.ok) {
        if (session === name) {
          setSession("");
          setPdfs([]);
          setMessages([]);
        }
        await loadSessions();
        setStatus("Session deleted");
      }
    } catch (err) {
      console.error("Delete failed", err);
      setStatus("Delete failed");
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("session", session);

    setStatus("Uploading & Ingesting...");
    setLoading(true);

    try {
      const response = await fetch("http://127.0.0.1:8000/api/upload/", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      setStatus(data.message || "Upload complete");
      loadPdfs();
    } catch (err) {
      setStatus("Upload failed");
    } finally {
      setLoading(false);
    }
  };

  const deletePdf = async (e, filename) => {
    e.stopPropagation();
    if (!window.confirm(`Remove ${filename} from this session?`)) return;

    try {
      const res = await fetch("http://127.0.0.1:8000/api/delete/", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, filename }),
      });
      if (res.ok) {
        loadPdfs();
        setSelectedPdfs(prev => prev.filter(p => p !== filename));
      }
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  const askQuestion = async (e) => {
    e?.preventDefault();
    if (!question.trim() || loading) return;

    const userMsg = { role: "user", text: question };
    setMessages(prev => [...prev, userMsg]);
    setQuestion("");
    setLoading(true);
    setStatus("Thinking...");

    try {
      const response = await fetch("http://127.0.0.1:8000/api/ask/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: userMsg.text,
          sources: selectedPdfs,
          session,
        }),
      });

      const data = await response.json();
      if (response.ok) {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: data.answer,
          citations: data.citations || []
        }]);
        setStatus("Ready");
      } else {
        throw new Error(data.error);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: "assistant",
        text: "Error: " + err.message,
        isError: true
      }]);
      setStatus("Error occurred");
    } finally {
      setLoading(false);
    }
  };

  const togglePdf = (filename) => {
    setSelectedPdfs(prev =>
      prev.includes(filename)
        ? prev.filter(f => f !== filename)
        : [...prev, filename]
    );
  };

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Scientific Navigator</h1>
        </div>

        <div className="sidebar-scroll">
          <div className="session-config">
            <span className="section-label" onClick={() => setIsSessionsOpen(!isSessionsOpen)}>
              Your Sessions
              <span className={`toggle-icon ${isSessionsOpen ? 'open' : ''}`}>▶</span>
            </span>

            <div className={`session-list ${isSessionsOpen ? '' : 'collapsed'}`}
              style={{ maxHeight: isSessionsOpen ? '1000px' : '0' }}>
              {sessions.map((s, i) => (
                <div
                  key={i}
                  className={`session-item ${session === s.name ? 'active' : ''}`}
                  onClick={() => setSession(s.name)}
                >
                  <div className="session-content">
                    <span className="session-item-icon">📁</span>
                    {s.name}
                  </div>
                  <button
                    className="delete-session-btn"
                    onClick={(e) => deleteSession(e, s.name)}
                    title="Delete Session"
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>

            <span className="section-label">New Session</span>
            <form className="input-group" onSubmit={handleCreateSession}>
              <input
                type="text"
                value={newSessionName}
                onChange={(e) => setNewSessionName(e.target.value)}
                placeholder="Session name..."
              />
              <button type="submit" className="btn-icon">
                +
              </button>
            </form>
          </div>

          <div className="source-management">
            <span className="section-label">Sources ({pdfs.length})</span>

            <div className="upload-zone" onClick={() => fileInputRef.current.click()}>
              <p>+ Add Document</p>
              <input
                type="file"
                className="hide-input"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".pdf"
              />
            </div>

            <div className="source-list">
              {pdfs.map((pdf, i) => (
                <div
                  key={i}
                  className={`source-item ${selectedPdfs.includes(pdf.filename) ? 'selected' : ''}`}
                  onClick={() => togglePdf(pdf.filename)}
                >
                  <input
                    type="checkbox"
                    checked={selectedPdfs.includes(pdf.filename)}
                    readOnly
                  />
                  <div className="source-info">
                    <span className="source-title" title={pdf.title || pdf.filename}>
                      {pdf.title || "Untitled Paper"}
                    </span>
                    <span className="source-meta">
                      {pdf.filename}
                    </span>
                  </div>
                  <button
                    className="delete-source-btn"
                    onClick={(e) => deletePdf(e, pdf.filename)}
                  >
                    &times;
                  </button>
                </div>
              ))}
              {pdfs.length === 0 && (
                <p className="muted" style={{ textAlign: 'center', fontSize: '0.8rem' }}>
                  No documents in this session.
                </p>
              )}
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        {status && <div className="status-indicator">{status}</div>}

        <div className="chat-container">
          {messages.length === 0 ? (
            <div className="welcome-screen">
              <h2>Welcome to your research workspace</h2>
              <p>Upload scientific papers, select them as context, and ask questions with strict citation grounding.</p>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`message ${msg.role}`}>
                <div className="message-content">
                  {msg.text}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="citations-grid">
                      {msg.citations.map((c, j) => (
                        <div key={j} className="citation-chip">
                          📖 {c.source} (p.{c.page})
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </div>

        <div className="input-area">
          <form onSubmit={askQuestion} className="chat-input-wrapper">
            <input
              type="text"
              placeholder={selectedPdfs.length > 0 ? "Ask a question about selected papers..." : "Select a source to start asking questions"}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={loading}
            />
            <button
              type="submit"
              className="btn-icon"
              disabled={loading || !question.trim()}
            >
              ➔
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

export default App;
