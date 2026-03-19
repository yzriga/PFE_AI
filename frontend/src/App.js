import { useState, useEffect, useRef } from "react";
import "./App.css";
import { api, API_BASE } from "./api";

const DEFAULT_SESSION_NAME = "Research Session";
const DEFAULT_SIDEBAR_ORDER = ["sessions", "uploadQueue", "externalSearch", "sources"];
const DEFAULT_SIDEBAR_WIDTH = 360;
const MIN_SIDEBAR_WIDTH = 280;
const MAX_SIDEBAR_WIDTH = 520;
const DEFAULT_PDF_DRAWER_WIDTH = 760;
const MIN_PDF_DRAWER_WIDTH = 520;
const MAX_PDF_DRAWER_WIDTH = 1280;

const MODE_CONFIG = {
  qa: {
    label: "QA",
    description: "Best for grounded answers on selected papers, or topic discovery when no source is selected.",
    minSources: 0,
  },
  compare: {
    label: "Compare",
    description: "Use when you want explicit agreements and disagreements across papers.",
    minSources: 2,
  },
  lit_review: {
    label: "Lit Review",
    description: "Use for a structured cross-paper synthesis of themes, differences, and open problems.",
    minSources: 2,
  },
  monitoring: {
    label: "Monitoring",
    description: "Inspect system performance and retrieval quality metrics.",
    minSources: 0,
  },
};

function IconFolder() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H10l2 2h6.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function IconSun() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 2.5v2.2M12 19.3v2.2M4.9 4.9l1.5 1.5M17.6 17.6l1.5 1.5M2.5 12h2.2M19.3 12h2.2M4.9 19.1l1.5-1.5M17.6 6.4l1.5-1.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function IconMoon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M16.8 14.8A7 7 0 0 1 9.2 5.7a8 8 0 1 0 9.1 9.1 6.3 6.3 0 0 1-1.5 0Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function IconChevron({ direction = "right" }) {
  const rotation = {
    right: "0deg",
    left: "180deg",
    down: "90deg",
    up: "-90deg",
  }[direction];

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" style={{ transform: `rotate(${rotation})` }}>
      <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconPin() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 4h8l-1.5 5 3 3v1H13v6l-1-1-1-5H6v-1l3-3L8 4Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconPencil() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m4 20 4.5-1 9-9a2.2 2.2 0 0 0-3.1-3.1l-9 9L4 20Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13.5 6.5 17.5 10.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function IconGrip() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 6.5h.01M9 12h.01M9 17.5h.01M15 6.5h.01M15 12h.01M15 17.5h.01" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

function App() {
  const clampSidebarWidth = (value) => {
    if (typeof window === "undefined") {
      return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, value));
    }
    const viewportCap = Math.min(MAX_SIDEBAR_WIDTH, Math.floor(window.innerWidth * 0.5));
    return Math.min(Math.max(viewportCap, MIN_SIDEBAR_WIDTH), Math.max(MIN_SIDEBAR_WIDTH, value));
  };
  const clampPdfDrawerWidth = (value) => {
    if (typeof window === "undefined") {
      return Math.min(MAX_PDF_DRAWER_WIDTH, Math.max(MIN_PDF_DRAWER_WIDTH, value));
    }
    const viewportCap = Math.min(MAX_PDF_DRAWER_WIDTH, Math.floor(window.innerWidth * 0.78));
    return Math.min(Math.max(viewportCap, MIN_PDF_DRAWER_WIDTH), Math.max(MIN_PDF_DRAWER_WIDTH, value));
  };

  const [session, setSession] = useState(DEFAULT_SESSION_NAME);
  const [sessions, setSessions] = useState([]);
  const [newSessionName, setNewSessionName] = useState("");
  const [isSessionsOpen, setIsSessionsOpen] = useState(true);
  const [isSidebarVisible, setIsSidebarVisible] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const raw = localStorage.getItem("sidebarWidth");
      const parsed = raw ? Number(raw) : DEFAULT_SIDEBAR_WIDTH;
      return Number.isFinite(parsed) ? clampSidebarWidth(parsed) : DEFAULT_SIDEBAR_WIDTH;
    } catch {
      return DEFAULT_SIDEBAR_WIDTH;
    }
  });
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const [sidebarOrder, setSidebarOrder] = useState(() => {
    try {
      const raw = localStorage.getItem("sidebarOrder");
      const parsed = raw ? JSON.parse(raw) : null;
      if (Array.isArray(parsed) && parsed.length === DEFAULT_SIDEBAR_ORDER.length) {
        return parsed;
      }
    } catch { }
    return DEFAULT_SIDEBAR_ORDER;
  });
  const [draggedSidebarSection, setDraggedSidebarSection] = useState(null);
  const [sidebarDropTarget, setSidebarDropTarget] = useState(null);
  const [pdfs, setPdfs] = useState([]);
  const [selectedPdfs, setSelectedPdfs] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [status, setStatus] = useState("");
  const [mode, setMode] = useState("qa");
  const [loading, setLoading] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem("theme") || "dark");
  const [pdfViewer, setPdfViewer] = useState(null);
  const [highlights, setHighlights] = useState([]);
  const [highlightNote, setHighlightNote] = useState("");
  const [highlightTags, setHighlightTags] = useState("");
  const [highlightSearch, setHighlightSearch] = useState("");
  const [highlightSearchResults, setHighlightSearchResults] = useState([]);
  const [highlightSearchLoading, setHighlightSearchLoading] = useState(false);
  const [isHighlightSearchOpen, setIsHighlightSearchOpen] = useState(false);
  const [highlightPanelView, setHighlightPanelView] = useState("search");
  const [allHighlights, setAllHighlights] = useState([]);
  const [allHighlightsLoading, setAllHighlightsLoading] = useState(false);
  const [pdfDrawerWidth, setPdfDrawerWidth] = useState(() => {
    try {
      const raw = localStorage.getItem("pdfDrawerWidth");
      const parsed = raw ? Number(raw) : DEFAULT_PDF_DRAWER_WIDTH;
      return Number.isFinite(parsed) ? clampPdfDrawerWidth(parsed) : DEFAULT_PDF_DRAWER_WIDTH;
    } catch {
      return DEFAULT_PDF_DRAWER_WIDTH;
    }
  });
  const [isPdfDrawerResizing, setIsPdfDrawerResizing] = useState(false);
  const [externalLoading, setExternalLoading] = useState(false);
  const [externalError, setExternalError] = useState("");
  const [uploadQueue, setUploadQueue] = useState([]);
  const [isUploadQueueCollapsed, setIsUploadQueueCollapsed] = useState(() => localStorage.getItem("uploadQueueCollapsed") === "true");
  const [isDragActive, setIsDragActive] = useState(false);
  const [sourceSearch, setSourceSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [sourceSort, setSourceSort] = useState("recent");
  const [relatedPanel, setRelatedPanel] = useState(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [editingSession, setEditingSession] = useState("");
  const [editingSessionName, setEditingSessionName] = useState("");
  const [selectedCitations, setSelectedCitations] = useState([]);
  const [selectedCitationNote, setSelectedCitationNote] = useState("");
  const [selectedCitationTags, setSelectedCitationTags] = useState("");
  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);
  const selectableTextRef = useRef(null);
  const sidebarResizeStartRef = useRef({ x: 0, width: DEFAULT_SIDEBAR_WIDTH });
  const pdfDrawerResizeStartRef = useRef({ x: 0, width: DEFAULT_PDF_DRAWER_WIDTH });
  const distinctSelectedCount = new Set(selectedPdfs).size;
  const activeModeConfig = MODE_CONFIG[mode];
  const totalQueries = metrics?.queries?.total || 0;
  const queryModeEntries = Object.entries(metrics?.queries?.by_mode || {}).sort((a, b) => b[1] - a[1]);
  const latencyTotal =
    (metrics?.queries?.retrieval_avg_ms || 0) +
    (metrics?.queries?.generation_avg_ms || 0) +
    (metrics?.queries?.orchestration_avg_ms || 0);
  const latencyBreakdown = [
    { label: "Retrieval", value: metrics?.queries?.retrieval_avg_ms || 0, tone: "retrieval" },
    { label: "Generation", value: metrics?.queries?.generation_avg_ms || 0, tone: "generation" },
    { label: "Orchestration", value: metrics?.queries?.orchestration_avg_ms || 0, tone: "orchestration" },
  ];
  const topErrors = metrics?.errors?.top_errors || [];
  const groundedAnswerRate = Math.max(
    0,
    100 - ((metrics?.grounding?.insufficient_evidence_rate || 0) * 100) - ((metrics?.grounding?.refusal_rate || 0) * 100)
  );
  const healthScore = Math.max(
    0,
    Math.min(
      100,
      Math.round(
        100 -
        ((metrics?.errors?.rate || 0) * 42) -
        ((metrics?.grounding?.refusal_rate || 0) * 28) -
        ((metrics?.grounding?.insufficient_evidence_rate || 0) * 20) +
        ((metrics?.grounding?.avg_confidence_score || 0) * 18)
      )
    )
  );
  const formatMetricMs = (value) => {
    if (!value) return "0ms";
    if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
    return `${value}ms`;
  };

  const externalSources = [
    { id: "openalex", label: "OpenAlex", hint: "Broad scholarly discovery with citation graph coverage" },
    { id: "europepmc", label: "Europe PMC", hint: "Biomedical literature with strong open-access coverage" },
    { id: "arxiv", label: "arXiv", hint: "Computer science, physics and math preprints" },
    { id: "pubmed", label: "PubMed", hint: "Biomedical and life-science publications" },
    { id: "semanticscholar", label: "Semantic Scholar", hint: "Citation graph and broad metadata search" },
    { id: "acl", label: "ACL", hint: "NLP and computational linguistics papers" },
    { id: "medrxiv", label: "medRxiv", hint: "Health-science preprints and early findings" },
  ];

  // Theme management
  useEffect(() => {
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("sidebarOrder", JSON.stringify(sidebarOrder));
  }, [sidebarOrder]);

  useEffect(() => {
    localStorage.setItem("sidebarWidth", String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    localStorage.setItem("pdfDrawerWidth", String(pdfDrawerWidth));
  }, [pdfDrawerWidth]);

  useEffect(() => {
    localStorage.setItem("uploadQueueCollapsed", String(isUploadQueueCollapsed));
  }, [isUploadQueueCollapsed]);

  useEffect(() => {
    if (!isSidebarResizing) return undefined;

    const handlePointerMove = (event) => {
      const nextWidth = sidebarResizeStartRef.current.width + (event.clientX - sidebarResizeStartRef.current.x);
      setSidebarWidth(clampSidebarWidth(nextWidth));
    };

    const handlePointerUp = () => {
      setIsSidebarResizing(false);
    };

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", handlePointerUp);
    document.body.classList.add("sidebar-resizing");

    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
      document.body.classList.remove("sidebar-resizing");
    };
  }, [isSidebarResizing]);

  useEffect(() => {
    if (!isPdfDrawerResizing) return undefined;

    const handlePointerMove = (event) => {
      const nextWidth = pdfDrawerResizeStartRef.current.width - (event.clientX - pdfDrawerResizeStartRef.current.x);
      setPdfDrawerWidth(clampPdfDrawerWidth(nextWidth));
    };

    const handlePointerUp = () => {
      setIsPdfDrawerResizing(false);
    };

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", handlePointerUp);
    document.body.classList.add("pdf-drawer-resizing");

    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
      document.body.classList.remove("pdf-drawer-resizing");
    };
  }, [isPdfDrawerResizing]);

  useEffect(() => {
    const handleResize = () => {
      setSidebarWidth((current) => clampSidebarWidth(current));
      setPdfDrawerWidth((current) => clampPdfDrawerWidth(current));
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const toggleTheme = () => {
    setTheme(prev => prev === "dark" ? "light" : "dark");
  };


  // Initial load
  useEffect(() => {
    loadSessions();
  }, []);

  // Auto-load PDFs and history when session changes
  useEffect(() => {
    if (session) {
      loadPdfs();
      loadHistory();
    }
    setSelectedCitations([]);
    if (mode === 'monitoring') {
      loadMetrics();
    }
  }, [session, mode]);

  // Scroll to bottom of chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (pdfViewer?.filename) {
      loadHighlightsForDocument(pdfViewer.filename);
    }
  }, [pdfViewer?.filename, pdfs]);

  useEffect(() => {
    const q = highlightSearch.trim();
    if (!session || !q) {
      setHighlightSearchResults([]);
      setHighlightSearchLoading(false);
      return;
    }

    setHighlightSearchLoading(true);
    const timer = setTimeout(() => {
      runHighlightSearch(q);
    }, 350);

    return () => clearTimeout(timer);
  }, [highlightSearch, session]);

  useEffect(() => {
    if (!isHighlightSearchOpen || highlightPanelView !== "saved" || !session) return;
    loadSessionHighlights();
  }, [isHighlightSearchOpen, highlightPanelView, session]);

  const loadSessions = async () => {
    try {
      let data = await api.listSessions();
      if (!data || data.length === 0) {
        await api.createSession(session || DEFAULT_SESSION_NAME);
        data = await api.listSessions();
      }
      setSessions(data || []);
      if (data?.length > 0 && !data.some((item) => item.name === session)) {
        setSession(data[0].name);
      }
    } catch (err) {
      console.error("Failed to load sessions", err);
    }
  };

  const moveSidebarSection = (sectionId, direction) => {
    setSidebarOrder((prev) => {
      const index = prev.indexOf(sectionId);
      if (index < 0) return prev;
      const target = direction === "up" ? index - 1 : index + 1;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const placeSidebarSection = (sourceId, targetId) => {
    if (!sourceId || !targetId || sourceId === targetId) return;
    setSidebarOrder((prev) => {
      const next = [...prev];
      const sourceIndex = next.indexOf(sourceId);
      const targetIndex = next.indexOf(targetId);
      if (sourceIndex < 0 || targetIndex < 0) return prev;
      const [moved] = next.splice(sourceIndex, 1);
      const insertAt = sourceIndex < targetIndex ? targetIndex - 1 : targetIndex;
      next.splice(insertAt, 0, moved);
      return next;
    });
  };

  const handleSidebarDragStart = (sectionId, event) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", sectionId);
    setDraggedSidebarSection(sectionId);
    setSidebarDropTarget(null);
  };

  const handleSidebarDragOver = (sectionId, event) => {
    event.preventDefault();
    if (draggedSidebarSection && draggedSidebarSection !== sectionId) {
      setSidebarDropTarget(sectionId);
    }
  };

  const handleSidebarDrop = (sectionId, event) => {
    event.preventDefault();
    const sourceId = draggedSidebarSection || event.dataTransfer.getData("text/plain");
    placeSidebarSection(sourceId, sectionId);
    setDraggedSidebarSection(null);
    setSidebarDropTarget(null);
  };

  const handleSidebarDragEnd = () => {
    setDraggedSidebarSection(null);
    setSidebarDropTarget(null);
  };

  const loadHistory = async () => {
    try {
      const data = await api.listHistory(session);
      setMessages(data?.history || []);
    } catch (err) {
      console.error("Failed to load history", err);
    }
  };

  const loadPdfs = async () => {
    try {
      const data = await api.listPdfs(session);
      setPdfs(data?.pdfs || []);
    } catch (err) {
      console.error("Failed to load PDFs", err);
    }
  };

  const loadMetrics = async () => {
    try {
      const data = await api.listMetrics();
      setMetrics(data);
    } catch (err) {
      console.error("Failed to load metrics", err);
    }
  };

  const normalizeForMatch = (text = "") =>
    text
      .toLowerCase()
      .replace(/[^\w\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  const choosePrecisePhrase = (snippet, pageText) => {
    const cleanSnippet = (snippet || "").replace(/\s+/g, " ").trim();
    const cleanPage = normalizeForMatch(pageText || "");
    if (!cleanSnippet || !cleanPage) return "";

    const words = cleanSnippet.split(" ").filter(Boolean);
    if (words.length < 4) return "";

    const windowSizes = [16, 14, 12, 10, 8, 6];
    for (const size of windowSizes) {
      if (words.length < size) continue;
      for (let i = 0; i <= words.length - size; i++) {
        const phrase = words.slice(i, i + size).join(" ").trim();
        const phraseNorm = normalizeForMatch(phrase);
        if (phraseNorm.length < 24) continue;
        if (cleanPage.includes(phraseNorm)) {
          return phrase;
        }
      }
    }

    return "";
  };

  const chooseFallbackSearch = (snippet) => {
    const cleanSnippet = normalizeForMatch(snippet || "");
    if (!cleanSnippet) return "";

    const words = cleanSnippet.split(" ").filter(Boolean);
    if (words.length === 0) return "";

    return words.slice(0, 12).join(" ");
  };

  const citationKey = (citation) => {
    const page = citation?.pageOneIndexed ? Number(citation.page || 1) : Number(citation.page || 0) + 1;
    return `${citation?.source || citation?.filename || "unknown"}::${page}::${(citation?.snippet || "").slice(0, 120)}`;
  };

  const buildPdfViewerUrl = ({ docUrl, page, snippet, precisePhrase, shouldUsePdfViewer }) => {
    if (!shouldUsePdfViewer) return "";
    const searchQuery = precisePhrase || chooseFallbackSearch(snippet);
    const usePhraseMatch = Boolean(precisePhrase);
    return `https://mozilla.github.io/pdf.js/web/viewer.html?file=${encodeURIComponent(docUrl)}#page=${page}${searchQuery ? `&search=${encodeURIComponent(searchQuery)}${usePhraseMatch ? "&phrase=true" : ""}` : ""}`;
  };

  const loadViewerForSource = async ({ filename, page = 1, snippet = "", startOffset = null, endOffset = null }) => {
    const cleanSnippet = (snippet || "").trim();
    let precisePhrase = "";
    let textPreview = "";
    let contentType = "pdf";
    const doc = pdfs.find((p) => p.filename === filename);
    const docUrl = doc?.file_url ? `${API_BASE}${doc.file_url}` : `${API_BASE}/media/pdfs/${encodeURIComponent(filename)}`;
    const isSummaryOnly = Boolean(doc?.error_message?.includes("Summary-only"));
    const isPdfFilename = filename?.toLowerCase().endsWith(".pdf");

    if (doc) {
      try {
        const payload = await api.getDocumentPageText(doc.id, page);
        textPreview = payload?.text || "";
        contentType = payload?.content_type || "pdf";
        precisePhrase = cleanSnippet ? choosePrecisePhrase(cleanSnippet, payload?.text || "") : "";
        const resolvedPageCount = Number(payload?.page_count || doc?.page_count || 1);
        setPdfViewer({
          filename,
          page,
          snippet: cleanSnippet,
          viewerUrl: buildPdfViewerUrl({
            docUrl,
            page,
            snippet: cleanSnippet,
            precisePhrase,
            shouldUsePdfViewer: isPdfFilename && !isSummaryOnly && contentType === "pdf",
          }),
          textPreview,
          mode: isPdfFilename && !isSummaryOnly && contentType === "pdf" ? "pdf" : "text",
          precisePhrase,
          startOffset,
          endOffset,
          pageCount: resolvedPageCount,
        });
        return;
      } catch (err) {
        console.error("Failed fetching page text for precise highlight", err);
      }
    }

    const shouldUsePdfViewer = isPdfFilename && !isSummaryOnly && contentType === "pdf";
    const viewerUrl = buildPdfViewerUrl({
      docUrl,
      page,
      snippet: cleanSnippet,
      precisePhrase,
      shouldUsePdfViewer,
    });

    setPdfViewer({
      filename,
      page,
      snippet: cleanSnippet,
      viewerUrl,
      textPreview,
      mode: shouldUsePdfViewer ? "pdf" : "text",
      precisePhrase,
      startOffset,
      endOffset,
      pageCount: Number(doc?.page_count || 1),
    });
  };

  const openCitationViewer = async (citation) => {
    const filename = citation.source;
    const page = citation.pageOneIndexed
      ? Number(citation.page || 1)
      : Number(citation.page || 0) + 1;
    const snippet = (citation.snippet || "").trim();
    await loadViewerForSource({
      filename,
      page,
      snippet,
      startOffset: 0,
      endOffset: snippet ? snippet.length : null,
    });
  };

  const openSourceViewer = async (pdf) => {
    await loadViewerForSource({
      filename: pdf.filename,
      page: 1,
      snippet: "",
    });
  };

  const changePdfViewerPage = async (delta) => {
    if (!pdfViewer?.filename) return;
    const nextPage = Math.min(Math.max(1, Number(pdfViewer.page || 1) + delta), Number(pdfViewer.pageCount || 1));
    if (nextPage === pdfViewer.page) return;
    await loadViewerForSource({
      filename: pdfViewer.filename,
      page: nextPage,
      snippet: "",
    });
  };

  const updateViewerSelection = ({ snippet, startOffset, endOffset }) => {
    if (!pdfViewer) return;
    const nextSnippet = (snippet || "").trim();
    const precisePhrase = nextSnippet ? choosePrecisePhrase(nextSnippet, pdfViewer.textPreview || "") : "";
    const doc = pdfs.find((p) => p.filename === pdfViewer.filename);
    const docUrl = doc?.file_url ? `${API_BASE}${doc.file_url}` : `${API_BASE}/media/pdfs/${encodeURIComponent(pdfViewer.filename)}`;
    const viewerUrl = buildPdfViewerUrl({
      docUrl,
      page: pdfViewer.page,
      snippet: nextSnippet,
      precisePhrase,
      shouldUsePdfViewer: pdfViewer.mode === "pdf",
    });

    setPdfViewer((prev) => prev ? ({
      ...prev,
      snippet: nextSnippet,
      precisePhrase,
      startOffset,
      endOffset,
      viewerUrl,
    }) : prev);
  };

  const captureViewerSelection = () => {
    const container = selectableTextRef.current;
    const selection = window.getSelection?.();
    if (!container || !selection || selection.rangeCount === 0 || selection.isCollapsed) return;

    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) return;

    const selectedText = selection.toString().replace(/\s+/g, " ").trim();
    if (!selectedText) return;

    const preRange = range.cloneRange();
    preRange.selectNodeContents(container);
    preRange.setEnd(range.startContainer, range.startOffset);
    const startOffset = preRange.toString().length;
    const endOffset = startOffset + range.toString().length;

    updateViewerSelection({
      snippet: selectedText,
      startOffset,
      endOffset,
    });
  };

  const toggleCitationSelection = (citation, e) => {
    e?.stopPropagation();
    const key = citationKey(citation);
    setSelectedCitations((prev) => {
      const exists = prev.some((item) => citationKey(item) === key);
      if (exists) {
        return prev.filter((item) => citationKey(item) !== key);
      }
      return [...prev, citation];
    });
  };

  const saveSelectedCitationsAsHighlights = async () => {
    if (selectedCitations.length === 0) return;
    const tags = selectedCitationTags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      for (const citation of selectedCitations) {
        const filename = citation.source || citation.filename;
        const doc = pdfs.find((item) => item.filename === filename);
        if (!doc) continue;
        const page = citation.pageOneIndexed
          ? Number(citation.page || 1)
          : Number(citation.page || 0) + 1;
        const text = citation.snippet || "";
        if (!text) continue;
        await api.createHighlight({
          document_id: doc.id,
          page,
          start_offset: 0,
          end_offset: text.length,
          text,
          note: selectedCitationNote,
          tags,
        });
      }
      if (pdfViewer?.filename) {
        await loadHighlightsForDocument(pdfViewer.filename);
      }
      if (isHighlightSearchOpen && highlightPanelView === "saved") {
        await loadSessionHighlights();
      }
      setSelectedCitations([]);
      setSelectedCitationNote("");
      setSelectedCitationTags("");
      setStatus("Selected citations saved to highlights");
    } catch (err) {
      setStatus("Failed to save selected citations");
    }
  };

  const loadHighlightsForDocument = async (filename) => {
    const doc = pdfs.find((p) => p.filename === filename);
    if (!doc) return setHighlights([]);

    try {
      const data = await api.listHighlights(doc.id);
      setHighlights(data?.highlights || []);
    } catch (err) {
      console.error("Failed to load highlights", err);
    }
  };

  const createHighlightFromCitation = async () => {
    if (!pdfViewer?.filename || !pdfViewer?.snippet) return;
    const doc = pdfs.find((p) => p.filename === pdfViewer.filename);
    if (!doc) return;

    const tags = highlightTags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    try {
        await api.createHighlight({
          document_id: doc.id,
          page: pdfViewer.page,
          start_offset: pdfViewer.startOffset ?? 0,
          end_offset: pdfViewer.endOffset ?? pdfViewer.snippet.length,
          text: pdfViewer.snippet,
          note: highlightNote,
          tags,
      });
      setHighlightNote("");
      setHighlightTags("");
      await loadHighlightsForDocument(pdfViewer.filename);
      if (isHighlightSearchOpen && highlightPanelView === "saved") {
        await loadSessionHighlights();
      }
      setStatus("Highlight saved");
    } catch (err) {
      setStatus("Failed to save highlight");
    }
  };

  const deleteHighlight = async (highlightId) => {
    try {
      await api.deleteHighlight(highlightId);
      if (pdfViewer?.filename) {
        await loadHighlightsForDocument(pdfViewer.filename);
      }
      if (isHighlightSearchOpen && highlightPanelView === "saved") {
        await loadSessionHighlights();
      }
    } catch (err) {
      console.error("Failed to delete highlight", err);
    }
  };

  const runHighlightSearch = async (query) => {
    if (!query || !session) return;
    try {
      const data = await api.searchHighlights({ session, q: query });
      setHighlightSearchResults(data?.results || []);
    } catch (err) {
      console.error("Highlight search failed", err);
      setHighlightSearchResults([]);
    } finally {
      setHighlightSearchLoading(false);
    }
  };

  const searchMyHighlights = async (e) => {
    e?.preventDefault();
    const q = highlightSearch.trim();
    if (!q || !session) return;
    setHighlightSearchLoading(true);
    await runHighlightSearch(q);
  };

  const loadSessionHighlights = async () => {
    if (!session) return;
    setAllHighlightsLoading(true);
    try {
      const data = await api.listHighlights({ session });
      setAllHighlights(data?.highlights || []);
    } catch (err) {
      console.error("Failed to load session highlights", err);
      setAllHighlights([]);
    } finally {
      setAllHighlightsLoading(false);
    }
  };

  const handleCreateSession = async (e) => {
    e?.preventDefault();
    if (!newSessionName.trim()) return;

    setStatus("Creating session...");
    try {
      await api.createSession(newSessionName);
      setSession(newSessionName);
      setNewSessionName("");
      await loadSessions();
      setStatus("Session ready");
    } catch (err) {
      setStatus("Error creating session");
    }
  };

  const startRenamingSession = (name) => {
    setEditingSession(name);
    setEditingSessionName(name);
  };

  const cancelRenamingSession = () => {
    setEditingSession("");
    setEditingSessionName("");
  };

  const submitSessionRename = async (originalName) => {
    const nextName = editingSessionName.trim();
    if (!nextName || nextName === originalName) {
      cancelRenamingSession();
      return;
    }
    setStatus("Renaming session...");
    try {
      const data = await api.updateSession(originalName, { name: nextName });
      if (session === originalName) {
        setSession(data?.session || nextName);
      }
      await loadSessions();
      cancelRenamingSession();
      setStatus("Session renamed");
    } catch (err) {
      setStatus(err?.message || "Rename failed");
    }
  };

  const toggleSessionPin = async (sessionItem) => {
    try {
      await api.updateSession(sessionItem.name, { pinned: !sessionItem.pinned });
      await loadSessions();
      setStatus(sessionItem.pinned ? "Session unpinned" : "Session pinned");
    } catch (err) {
      setStatus(err?.message || "Pin update failed");
    }
  };

  const deleteSession = async (e, name) => {
    e.stopPropagation();
    if (!window.confirm(`Delete entire workflow for "${name}"? This cannot be undone.`)) return;

    setStatus("Deleting session data...");
    try {
      await api.deleteSession(name);
      if (session === name) {
        setSession("");
        setPdfs([]);
        setMessages([]);
      }
      await loadSessions();
      setStatus("Session deleted");
    } catch (err) {
      console.error("Delete failed", err);
      setStatus("Delete failed");
    }
  };

  const clearAllUploads = () => {
    setUploadQueue((prev) => prev.filter((item) => item.status === "uploading"));
  };

  const [arxivQuery, setArxivQuery] = useState("");
  const [searchSource, setSearchSource] = useState("openalex");
  const [arxivResults, setArxivResults] = useState([]);
  const [isArxivOpen, setIsArxivOpen] = useState(false);
  const [previewId, setPreviewId] = useState(null);
  const activeExternalSource = externalSources.find((src) => src.id === searchSource) || externalSources[0];

  const visiblePdfs = [...pdfs]
    .filter((pdf) => {
      const search = sourceSearch.trim().toLowerCase();
      const title = (pdf.title || "").toLowerCase();
      const filename = (pdf.filename || "").toLowerCase();
      const sourceType = (pdf.source_type || "manual").toLowerCase();
      const matchesSearch = !search || title.includes(search) || filename.includes(search) || sourceType.includes(search);

      if (!matchesSearch) return false;
      if (sourceFilter === "all") return true;
      if (sourceFilter === "summary") return Boolean(pdf.error_message?.includes("Summary-only"));
      if (sourceFilter === "external") return (pdf.source_type || "manual") !== "manual";
      return (pdf.status || "").toLowerCase() === sourceFilter;
    })
    .sort((a, b) => {
      if (sourceSort === "title") {
        return (a.title || a.filename).localeCompare(b.title || b.filename);
      }
      if (sourceSort === "status") {
        return (a.status || "").localeCompare(b.status || "");
      }
      if (sourceSort === "source") {
        return (a.source_type || "manual").localeCompare(b.source_type || "manual");
      }
      return new Date(b.uploaded_at || 0) - new Date(a.uploaded_at || 0);
    });

  const queueSummary = {
    active: uploadQueue.filter((item) => item.status === "queued" || item.status === "uploading").length,
    failed: uploadQueue.filter((item) => item.status === "failed").length,
    completed: uploadQueue.filter((item) => item.status === "completed").length,
  };

  // Poll for processing PDFs
  useEffect(() => {
    const processingPdfs = pdfs.filter(p => p.status === 'QUEUED' || p.status === 'UPLOADED' || p.status === 'PROCESSING');
    if (processingPdfs.length > 0) {
      const interval = setInterval(() => {
        loadPdfs();
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [pdfs]);

  useEffect(() => {
    const activeUpload = uploadQueue.find((item) => item.status === "uploading");
    if (activeUpload) return;

    const nextUpload = uploadQueue.find((item) => item.status === "queued");
    if (!nextUpload) return;

    const controller = new AbortController();
    setUploadQueue((prev) =>
      prev.map((item) =>
        item.id === nextUpload.id
          ? { ...item, status: "uploading", controller, progress: item.progress || 0 }
          : item
      )
    );
    setStatus(`Uploading ${nextUpload.file.name}...`);

    const formData = new FormData();
    formData.append("file", nextUpload.file);
    formData.append("session", nextUpload.session);
    formData.__onProgress = (progress) => {
      setUploadQueue((prev) =>
        prev.map((item) => (item.id === nextUpload.id ? { ...item, progress } : item))
      );
    };
    formData.__signal = controller.signal;

    api.uploadPdf(formData)
      .then((data) => {
        setUploadQueue((prev) =>
          prev.map((item) =>
            item.id === nextUpload.id
              ? { ...item, status: "completed", progress: 100, controller: null, response: data }
              : item
          )
        );
        setStatus(data?.message || `${nextUpload.file.name} queued for ingestion`);
        loadPdfs();
      })
      .catch((err) => {
        setUploadQueue((prev) =>
          prev.map((item) =>
            item.id === nextUpload.id
              ? {
                ...item,
                status: err?.aborted ? "canceled" : "failed",
                controller: null,
                error: err?.message || "Upload failed",
              }
              : item
          )
        );
        setStatus(err?.aborted ? `Canceled ${nextUpload.file.name}` : `Upload failed for ${nextUpload.file.name}`);
      });
  }, [uploadQueue]);

  const enqueueFiles = (files) => {
    const incoming = Array.from(files || []);
    if (incoming.length === 0) return;

    const queuedItems = incoming.map((file) => ({
      id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      session,
      progress: 0,
      status: file.name.toLowerCase().endsWith(".pdf") ? "queued" : "failed",
      error: file.name.toLowerCase().endsWith(".pdf") ? "" : "Only PDF files are allowed",
      controller: null,
    }));

    setUploadQueue((prev) => [...queuedItems, ...prev].slice(0, 20));
    const validCount = queuedItems.filter((item) => item.status === "queued").length;
    setStatus(validCount > 0 ? `Queued ${validCount} file${validCount > 1 ? "s" : ""} for upload` : "Only PDF files can be uploaded");
  };

  const handleFileUpload = async (e) => {
    enqueueFiles(e.target.files);
    e.target.value = "";
  };

  const retryQueuedUpload = (entryId) => {
    setUploadQueue((prev) =>
      prev.map((item) =>
        item.id === entryId
          ? { ...item, status: "queued", progress: 0, error: "", controller: null }
          : item
      )
    );
  };

  const cancelQueuedUpload = (entryId) => {
    setUploadQueue((prev) =>
      prev.map((item) => {
        if (item.id !== entryId) return item;
        if (item.status === "uploading" && item.controller) {
          item.controller.abort();
          return { ...item };
        }
        return { ...item, status: "canceled", controller: null };
      })
    );
  };

  const removeQueuedUpload = (entryId) => {
    setUploadQueue((prev) => prev.filter((item) => item.id !== entryId));
  };

  const searchExternal = async (e) => {
    e?.preventDefault();
    if (!arxivQuery.trim()) return;
    setStatus(`Searching ${searchSource.toUpperCase()}...`);
    setExternalLoading(true);
    setExternalError("");
    try {
      const data = await api.searchExternal({ q: arxivQuery, source: searchSource });
      setArxivResults(data?.results || []);
      setStatus(data?.results?.length > 0 ? "Search complete" : "No results found");
    } catch (err) {
      if (err.status === 429) {
        setExternalError(`${searchSource.toUpperCase()}: Too many requests. Please wait.`);
      } else {
        setExternalError(err?.message || "External search failed");
      }
      setStatus("External search failed");
      setArxivResults([]);
    } finally {
      setExternalLoading(false);
    }
  };

  const importExternal = async (id, provider = searchSource) => {
    setStatus(`Importing from ${provider.toUpperCase()}...`);
    try {
      await api.importExternal({ id, source: provider, session });
      setStatus("Import initiated");
      loadPdfs();
    } catch (err) {
      setStatus("Import failed: " + (err?.message || "Unknown"));
    }
  };

  const loadRelatedPapers = async (pdf) => {
    setRelatedLoading(true);
    setStatus(`Discovering related papers for ${pdf.title || pdf.filename}...`);
    try {
      const data = await api.getRelatedPapers({ documentId: pdf.id, limit: 6 });
      setRelatedPanel({
        documentId: pdf.id,
        filename: pdf.filename,
        title: pdf.title || pdf.filename,
        ...data,
      });
      setStatus("Related papers loaded");
    } catch (err) {
      setStatus(err?.message || "Related paper discovery failed");
    } finally {
      setRelatedLoading(false);
    }
  };

  const askQuestion = async (e) => {
    e?.preventDefault();
    if (!question.trim() || loading) return;
    if (mode !== "monitoring" && distinctSelectedCount < activeModeConfig.minSources) {
      setStatus(
        mode === "lit_review"
          ? "Literature Review needs at least 2 selected papers. Use QA for a single-paper summary."
          : `Select at least ${activeModeConfig.minSources} papers for ${activeModeConfig.label}.`
      );
      return;
    }

    const userMsg = { role: "user", text: `${mode === 'qa' ? '' : '[' + mode.toUpperCase() + '] '}${question}` };
    setMessages(prev => [...prev, userMsg]);
    setQuestion("");
    setLoading(true);
    setStatus("Thinking...");

    try {
      const data = await api.ask({
        question: question,
        sources: selectedPdfs,
        session,
        mode: mode,
      });

      if (mode === "compare") {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: `Comparison for: "${question}"`,
          comparison: data,
          citations: data.citations || [],
        }]);
      } else if (mode === "lit_review") {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: data.content,
          title: data.title || "Literature Review",
          citations: data.citations || [],
          reviewStatus: data.review_status || "normal_review",
          reviewWarning: data.warning || "",
          reviewDiagnostics: data.review_diagnostics || null,
        }]);
      } else {
        setMessages(prev => [...prev, {
          role: "assistant",
          text: data.answer,
          citations: data.citations || [],
          suggestedSources: data.suggested_sources || [],
          discoveryMode: data.discovery_mode || "",
          sourceBasis: data.source_basis || "",
        }]);
      }
      setStatus("Ready");
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
    const pdf = pdfs.find(p => p.filename === filename);
    // Be resilient: if status is missing, assume it's okay (indexed)
    const isReady = !pdf?.status || pdf.status === 'INDEXED';
    if (!isReady) return;

    setSelectedPdfs(prev =>
      prev.includes(filename)
        ? prev.filter(f => f !== filename)
        : [...prev, filename]
    );
  };

  const deletePdf = async (e, filename) => {
    e.stopPropagation();
    if (!window.confirm(`Remove ${filename} from this session?`)) return;

    try {
      await api.deletePdf({ session, filename });
      loadPdfs();
      setSelectedPdfs(prev => prev.filter(p => p !== filename));
    } catch (err) {
      console.error("Delete failed", err);
    }
  };

  const retryPdfIngestion = async (e, pdf) => {
    e.stopPropagation();
    setStatus(`Retrying ingestion for ${pdf.filename}...`);
    try {
      const data = await api.retryDocument(pdf.id);
      setStatus(data?.message || "Retry initiated");
      await loadPdfs();
    } catch (err) {
      setStatus(err?.message || "Retry failed");
    }
  };

  const handleUploadDragOver = (e) => {
    e.preventDefault();
    setIsDragActive(true);
  };

  const handleUploadDragLeave = (e) => {
    e.preventDefault();
    setIsDragActive(false);
  };

  const handleUploadDrop = (e) => {
    e.preventDefault();
    setIsDragActive(false);
    enqueueFiles(e.dataTransfer.files);
  };

  const startSidebarResize = (event) => {
    event.preventDefault();
    sidebarResizeStartRef.current = {
      x: event.clientX,
      width: sidebarWidth,
    };
    setIsSidebarResizing(true);
  };

  const startPdfDrawerResize = (event) => {
    event.preventDefault();
    pdfDrawerResizeStartRef.current = {
      x: event.clientX,
      width: pdfDrawerWidth,
    };
    setIsPdfDrawerResizing(true);
  };

  return (
    <div
      className={`app-layout ${theme === 'light' ? 'light-mode' : ''} ${isSidebarVisible ? '' : 'sidebar-hidden'} ${isSidebarResizing ? 'sidebar-resizing' : ''}`}
      style={{ "--sidebar-width": `${sidebarWidth}px` }}
    >
      {/* Sidebar */}
      {isSidebarVisible && <aside className="sidebar">
        <div className="sidebar-header">
          <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
            <h1>Scientific Navigator</h1>
            <button
              className="theme-toggle"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === "dark" ? <IconSun /> : <IconMoon />}
            </button>
          </div>
        </div>

        <div className="sidebar-scroll">
          <div
            className={`sidebar-panel session-config ${draggedSidebarSection === "sessions" ? "dragging" : ""} ${sidebarDropTarget === "sessions" ? "drag-target" : ""}`}
            style={{ order: sidebarOrder.indexOf("sessions") }}
            onDragOver={(e) => handleSidebarDragOver("sessions", e)}
            onDrop={(e) => handleSidebarDrop("sessions", e)}
          >
            <div className="section-header">
              <span className="section-label" onClick={() => setIsSessionsOpen(!isSessionsOpen)}>
                Your Sessions
                <span className={`toggle-icon ${isSessionsOpen ? 'open' : ''}`}>{">"}</span>
              </span>
              <div className="panel-order-controls">
                <button
                  className="icon-btn drag-handle-btn"
                  draggable="true"
                  onDragStart={(e) => handleSidebarDragStart("sessions", e)}
                  onDragEnd={handleSidebarDragEnd}
                  title="Drag to reorder panels"
                >
                  <IconGrip />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("sessions", "up")} title="Move section up">
                  <IconChevron direction="up" />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("sessions", "down")} title="Move section down">
                  <IconChevron direction="down" />
                </button>
              </div>
            </div>

            <div className={`session-list ${isSessionsOpen ? '' : 'collapsed'}`}
              style={{ maxHeight: isSessionsOpen ? '1000px' : '0' }}>
              {sessions.map((s, i) => (
                <div
                  key={i}
                  className={`session-item ${session === s.name ? 'active' : ''}`}
                  onClick={() => setSession(s.name)}
                >
                  <div className="session-content">
                    <span className="session-item-icon" aria-hidden="true">
                      <IconFolder />
                    </span>
                    {editingSession === s.name ? (
                      <form
                        className="session-edit-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          submitSessionRename(s.name);
                        }}
                      >
                        <input
                          type="text"
                          value={editingSessionName}
                          onChange={(e) => setEditingSessionName(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          autoFocus
                        />
                      </form>
                    ) : (
                      <span className="session-name-text">{s.name}</span>
                    )}
                  </div>
                  <div className="session-actions">
                    <button
                      className={`icon-btn ${s.pinned ? "active" : ""}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSessionPin(s);
                      }}
                      title={s.pinned ? "Unpin session" : "Pin session"}
                    >
                      <IconPin />
                    </button>
                    {editingSession === s.name ? (
                      <>
                        <button
                          className="text-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            submitSessionRename(s.name);
                          }}
                          title="Save session name"
                        >
                          Save
                        </button>
                        <button
                          className="text-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            cancelRenamingSession();
                          }}
                          title="Cancel rename"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="icon-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          startRenamingSession(s.name);
                        }}
                        title="Rename session"
                      >
                        <IconPencil />
                      </button>
                    )}
                    <button
                      className="delete-session-btn"
                      onClick={(e) => deleteSession(e, s.name)}
                      title="Delete Session"
                    >
                      &times;
                    </button>
                  </div>
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

          <div
            className={`sidebar-panel upload-queue-section ${draggedSidebarSection === "uploadQueue" ? "dragging" : ""} ${sidebarDropTarget === "uploadQueue" ? "drag-target" : ""}`}
            style={{ order: sidebarOrder.indexOf("uploadQueue") }}
            onDragOver={(e) => handleSidebarDragOver("uploadQueue", e)}
            onDrop={(e) => handleSidebarDrop("uploadQueue", e)}
          >
            <div className="section-header">
              <span className="section-label">Upload Queue</span>
              <div className="panel-order-controls">
                <button
                  className="icon-btn drag-handle-btn"
                  draggable="true"
                  onDragStart={(e) => handleSidebarDragStart("uploadQueue", e)}
                  onDragEnd={handleSidebarDragEnd}
                  title="Drag to reorder panels"
                >
                  <IconGrip />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("uploadQueue", "up")} title="Move section up">
                  <IconChevron direction="up" />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("uploadQueue", "down")} title="Move section down">
                  <IconChevron direction="down" />
                </button>
                <button className="icon-btn" onClick={() => setIsUploadQueueCollapsed((v) => !v)} title={isUploadQueueCollapsed ? "Expand queue" : "Collapse queue"}>
                  <IconChevron direction={isUploadQueueCollapsed ? "right" : "down"} />
                </button>
              </div>
            </div>
            <div className="upload-queue-header compact">
              <strong>{queueSummary.active} active</strong>
              <span className="muted">{queueSummary.failed} failed, {queueSummary.completed} done</span>
            </div>
            {!isUploadQueueCollapsed && (
              <>
                {uploadQueue.length > 0 ? (
                  <>
                    <div className="upload-queue-toolbar">
                      <button className="text-btn" onClick={clearAllUploads}>Clear All</button>
                    </div>
                    <div className="upload-queue-list">
                      {uploadQueue.map((item) => (
                        <div key={item.id} className={`upload-queue-item ${item.status}`}>
                          <div className="upload-queue-meta">
                            <span className="upload-queue-name" title={item.file.name}>{item.file.name}</span>
                            <span className="upload-queue-state">{item.status}{item.error ? ` - ${item.error}` : ""}</span>
                          </div>
                          <div className="upload-progress-track">
                            <div className="upload-progress-fill" style={{ width: `${item.progress || 0}%` }} />
                          </div>
                          <div className="upload-queue-actions">
                            {(item.status === "queued" || item.status === "uploading") && (
                              <button className="text-btn" onClick={() => cancelQueuedUpload(item.id)}>Cancel</button>
                            )}
                            {(item.status === "failed" || item.status === "canceled") && (
                              <button className="text-btn" onClick={() => retryQueuedUpload(item.id)}>Retry</button>
                            )}
                            {(item.status === "completed" || item.status === "failed" || item.status === "canceled") && (
                              <button className="text-btn" onClick={() => removeQueuedUpload(item.id)}>Clear</button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="muted">No queued uploads.</p>
                )}
              </>
            )}
          </div>

          <div
            className={`sidebar-panel source-management ${draggedSidebarSection === "externalSearch" ? "dragging" : ""} ${sidebarDropTarget === "externalSearch" ? "drag-target" : ""}`}
            style={{ order: sidebarOrder.indexOf("externalSearch") }}
            onDragOver={(e) => handleSidebarDragOver("externalSearch", e)}
            onDrop={(e) => handleSidebarDrop("externalSearch", e)}
          >
            <div className="section-header">
              <span className="section-label">External Search</span>
              <div className="panel-order-controls">
                <button
                  className="icon-btn drag-handle-btn"
                  draggable="true"
                  onDragStart={(e) => handleSidebarDragStart("externalSearch", e)}
                  onDragEnd={handleSidebarDragEnd}
                  title="Drag to reorder panels"
                >
                  <IconGrip />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("externalSearch", "up")} title="Move section up">
                  <IconChevron direction="up" />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("externalSearch", "down")} title="Move section down">
                  <IconChevron direction="down" />
                </button>
                <button className="text-btn" onClick={() => setIsArxivOpen(!isArxivOpen)}>
                  {isArxivOpen ? 'Close' : 'Open'}
                </button>
              </div>
            </div>

            {isArxivOpen && (
              <div className="arxiv-search-box">
                <div className="source-tabs">
                  {externalSources.map((src) => (
                    <button
                      key={src.id}
                      className={`source-tab ${searchSource === src.id ? "active" : ""}`}
                      onClick={() => {
                        setSearchSource(src.id);
                        setArxivResults([]);
                        setPreviewId(null);
                        setExternalError("");
                      }}
                    >
                      {src.label}
                    </button>
                  ))}

                </div>
                <p className="external-source-hint">{activeExternalSource.hint}</p>
                <form className="input-group" onSubmit={searchExternal}>
                  <input
                    type="text"
                    value={arxivQuery}
                    onChange={(e) => setArxivQuery(e.target.value)}
                    placeholder={`Search ${activeExternalSource.label}...`}
                  />
                  <button type="submit" className="btn-icon" disabled={externalLoading}>
                    {externalLoading ? "..." : "Go"}
                  </button>
                </form>
                {externalError && <p className="external-error">{externalError}</p>}
                <div className="arxiv-results">
                  {arxivResults.map((res, i) => (
                    <div key={i} className={`arxiv-result-item ${previewId === res.id ? 'expanded' : ''}`}>
                      <div className="arxiv-res-header" onClick={() => setPreviewId(previewId === res.id ? null : res.id)}>
                        <p className="arxiv-res-title">{res.title}</p>
                        <span className="expand-chevron">{previewId === res.id ? "v" : ">"}</span>
                      </div>

                      {previewId === res.id && (
                        <div className="arxiv-res-preview">
                          <p className="arxiv-meta"><strong>Authors:</strong> {res.authors?.join(', ')}</p>
                          <p className="arxiv-meta"><strong>Date:</strong> {res.date || "n/a"}</p>
                          <div className="arxiv-abstract-container">
                            <strong>Abstract:</strong>
                            <p className="arxiv-abstract">{res.abstract || "No abstract available."}</p>
                          </div>
                          <div className="arxiv-actions">
                            <a
                              href={res.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="arxiv-link-btn"
                              onClick={(e) => e.stopPropagation()}
                            >
                              Open Paper
                            </a>
                            <button
                              className="mini-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                importExternal(res.id, res.provider || searchSource);
                              }}
                            >
                              Import
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div
            className={`sidebar-panel source-management ${draggedSidebarSection === "sources" ? "dragging" : ""} ${sidebarDropTarget === "sources" ? "drag-target" : ""}`}
            style={{ order: sidebarOrder.indexOf("sources") }}
            onDragOver={(e) => handleSidebarDragOver("sources", e)}
            onDrop={(e) => handleSidebarDrop("sources", e)}
          >
            <div className="section-header">
              <span className="section-label">Sources ({pdfs.length})</span>
              <div className="panel-order-controls">
                <button
                  className="icon-btn drag-handle-btn"
                  draggable="true"
                  onDragStart={(e) => handleSidebarDragStart("sources", e)}
                  onDragEnd={handleSidebarDragEnd}
                  title="Drag to reorder panels"
                >
                  <IconGrip />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("sources", "up")} title="Move section up">
                  <IconChevron direction="up" />
                </button>
                <button className="icon-btn" onClick={() => moveSidebarSection("sources", "down")} title="Move section down">
                  <IconChevron direction="down" />
                </button>
                {visiblePdfs.length > 0 && (
                  <button
                    className="text-btn"
                    onClick={() => setSelectedPdfs(
                      selectedPdfs.length === visiblePdfs.length ? [] : visiblePdfs.map(p => p.filename)
                    )}
                  >
                    {selectedPdfs.length === visiblePdfs.length ? 'Deselect All' : 'Select All'}
                  </button>
                )}
              </div>
            </div>

            <div
              className={`upload-zone ${isDragActive ? "drag-active" : ""}`}
              onClick={() => fileInputRef.current.click()}
              onDragOver={handleUploadDragOver}
              onDragLeave={handleUploadDragLeave}
              onDrop={handleUploadDrop}
            >
              <p>{isDragActive ? "Drop PDFs to queue them" : "+ Add Documents"}</p>
              <span className="upload-zone-subtitle">Batch upload, drag and drop, or click to browse.</span>
              <input
                type="file"
                className="hide-input"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".pdf"
                multiple
              />
            </div>

            <div className="source-toolbar">
              <input
                type="text"
                value={sourceSearch}
                onChange={(e) => setSourceSearch(e.target.value)}
                placeholder="Search title, filename, or source..."
              />
              <div className="source-toolbar-row">
                <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                  <option value="all">All statuses</option>
                  <option value="indexed">Indexed</option>
                  <option value="queued">Queued</option>
                  <option value="processing">Processing</option>
                  <option value="failed">Failed</option>
                  <option value="summary">Summary-only</option>
                  <option value="external">External imports</option>
                </select>
                <select value={sourceSort} onChange={(e) => setSourceSort(e.target.value)}>
                  <option value="recent">Newest first</option>
                  <option value="title">Title A-Z</option>
                  <option value="status">Status</option>
                  <option value="source">Source type</option>
                </select>
              </div>
            </div>

            <div className="source-list">
              {visiblePdfs.map((pdf, i) => {
                const isReady = !pdf.status || pdf.status === 'INDEXED';
                return (
                  <div
                    key={i}
                    className={`source-item ${selectedPdfs.includes(pdf.filename) ? 'selected' : ''} ${!isReady ? 'disabled' : ''}`}
                    onClick={() => togglePdf(pdf.filename)}
                  >
                    <input
                      type="checkbox"
                      checked={selectedPdfs.includes(pdf.filename)}
                      disabled={!isReady}
                      readOnly
                    />
                    <div className="source-info">
                      <span className="source-title" title={pdf.title || pdf.filename}>
                        {pdf.title || "Untitled Paper"}
                      </span>
                      <span className="source-meta">
                        {pdf.filename} - <span className={`status-badge ${(pdf.error_message?.includes('Summary-only') ? 'summary' : (pdf.status || 'INDEXED').toLowerCase())}`}>
                          {pdf.error_message?.includes('Summary-only') ? 'SUMMARY' : (pdf.status || 'INDEXED')}
                        </span>
                        <span className="source-origin">{pdf.source_type || "manual"}</span>
                      </span>
                    </div>
                    <div className="source-actions">
                      <button
                        className="mini-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          openSourceViewer(pdf);
                        }}
                        title="Open source in reader"
                      >
                        Open
                      </button>
                      <button
                        className="discover-source-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          loadRelatedPapers(pdf);
                        }}
                        title="Discover related papers"
                        disabled={relatedLoading}
                      >
                        Discover
                      </button>
                      {pdf.status === "FAILED" && (
                        <button
                          className="retry-source-btn"
                          onClick={(e) => retryPdfIngestion(e, pdf)}
                          title="Retry ingestion"
                        >
                          Retry
                        </button>
                      )}
                      <button
                        className="delete-source-btn"
                        onClick={(e) => deletePdf(e, pdf.filename)}
                        title="Delete source"
                      >
                        &times;
                      </button>
                    </div>
                  </div>
                );
              })}
              {visiblePdfs.length === 0 && (
                <p className="muted" style={{ textAlign: 'center', fontSize: '0.8rem' }}>
                  {pdfs.length === 0 ? "No documents in this session." : "No documents match the current filters."}
                </p>
              )}
            </div>
            {relatedPanel && (
              <div className="related-panel">
                <div className="section-header">
                  <span className="section-label">Related Papers</span>
                  <button className="text-btn" onClick={() => setRelatedPanel(null)}>Close</button>
                </div>
                <p className="external-source-hint">
                  {relatedPanel.title} · {relatedPanel.graph_source === "semanticscholar" ? "citation graph" : "title-based discovery fallback"}
                </p>
                {["references", "citations", "related"].map((group) => (
                  <div key={group} className="related-group">
                    <h4>{group.charAt(0).toUpperCase() + group.slice(1)}</h4>
                    {(relatedPanel[group] || []).length === 0 ? (
                      <p className="muted">No items in this section.</p>
                    ) : (
                      (relatedPanel[group] || []).map((item) => (
                        <div key={`${group}-${item.id}`} className="related-item">
                          <div className="related-item-copy">
                            <strong>{item.title}</strong>
                            <p>{(item.authors || []).slice(0, 4).join(", ") || "Unknown authors"}</p>
                            <p className="muted">{item.year || "n/a"}</p>
                          </div>
                          <div className="arxiv-actions">
                            {item.url && (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="arxiv-link-btn"
                                onClick={(e) => e.stopPropagation()}
                              >
                                Open
                              </a>
                            )}
                            <button
                              className="mini-btn"
                              onClick={() => importExternal(item.id, item.provider || "semanticscholar")}
                            >
                              Import
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>}

      {isSidebarVisible && (
        <button
          type="button"
          className="sidebar-resize-handle"
          onMouseDown={startSidebarResize}
          aria-label="Resize sidebar"
          title="Drag to resize sidebar"
        />
      )}

      <button
        className={`sidebar-edge-toggle ${isSidebarVisible ? "visible" : "hidden"}`}
        onClick={() => setIsSidebarVisible((v) => !v)}
        title={isSidebarVisible ? "Hide sidebar" : "Show sidebar"}
        aria-label={isSidebarVisible ? "Hide sidebar" : "Show sidebar"}
      >
        <IconChevron direction={isSidebarVisible ? "left" : "right"} />
      </button>

      {/* Main Content */}
      <main className="main-content">
        <div className={`workspace-body ${pdfViewer ? "with-viewer" : ""}`}>
          <div className="conversation-pane">
            <div className="chat-container">
              {mode === 'monitoring' ? (
                <div className="monitoring-dashboard">
                  <div className="mode-selector compact monitoring-modes">
                    {['qa', 'compare', 'lit_review', 'monitoring'].map((m) => {
                      const config = MODE_CONFIG[m];
                      const minSourcesHint = config.minSources > 1 ? ` Requires at least ${config.minSources} sources.` : "";
                      return (
                        <button
                          key={m}
                          type="button"
                          className={`mode-btn compact ${mode === m ? 'active' : ''}`}
                          onClick={() => setMode(m)}
                          title={`${config.label}: ${config.description}${minSourcesHint}`}
                          aria-label={`${config.label}. ${config.description}${minSourcesHint}`}
                        >
                          {config.label}
                        </button>
                      );
                    })}
                  </div>
                  <h2>System Monitoring</h2>
                  {metrics ? (
                    <div className="monitoring-layout">
                      <div className="metrics-grid">
                        <div className="metric-card emphasis-card">
                          <h3>System Health</h3>
                          <p className="metric-value">{healthScore}</p>
                          <p className="metric-sub">Composite score from errors, refusals, evidence gaps, and confidence.</p>
                        </div>
                        <div className="metric-card">
                          <h3>Grounded Answer Rate</h3>
                          <p className="metric-value">{groundedAnswerRate.toFixed(1)}%</p>
                          <p className="metric-sub">Runs that did not end in refusal or low-evidence fallback.</p>
                        </div>
                        <div className="metric-card">
                          <h3>Average Latency</h3>
                          <p className="metric-value">{formatMetricMs(metrics.queries.latency_avg_ms)}</p>
                          <p className="metric-sub">Mean end-to-end response time.</p>
                        </div>
                        <div className="metric-card">
                          <h3>Total Queries</h3>
                          <p className="metric-value">{metrics.queries.total}</p>
                          <p className="metric-sub">Observed in the current reporting window.</p>
                        </div>
                        <div className="metric-card">
                          <h3>Error Rate</h3>
                          <p className="metric-value">{(metrics.errors.rate * 100).toFixed(1)}%</p>
                          <p className="metric-sub">{metrics.errors.count || 0} failed runs logged.</p>
                        </div>
                        <div className="metric-card">
                          <h3>Active Sessions</h3>
                          <p className="metric-value">{metrics.sessions?.active_count ?? 0}</p>
                          <p className="metric-sub">Distinct sessions with recent activity.</p>
                        </div>
                        {metrics.grounding && (
                          <>
                            <div className="metric-card">
                              <h3>Refusal Rate</h3>
                              <p className="metric-value">{(metrics.grounding.refusal_rate * 100).toFixed(1)}%</p>
                              <p className="metric-sub">{metrics.grounding.refusal_count} refusals</p>
                            </div>
                            <div className="metric-card">
                              <h3>Low Evidence Rate</h3>
                              <p className="metric-value">{(metrics.grounding.insufficient_evidence_rate * 100).toFixed(1)}%</p>
                              <p className="metric-sub">{metrics.grounding.insufficient_evidence_count} flagged runs</p>
                            </div>
                            <div className="metric-card">
                              <h3>Avg Chunks Retrieved</h3>
                              <p className="metric-value">{metrics.grounding.avg_retrieved_chunks}</p>
                              <p className="metric-sub">Signal for retrieval breadth.</p>
                            </div>
                            <div className="metric-card">
                              <h3>Avg Confidence</h3>
                              <p className="metric-value">{(metrics.grounding.avg_confidence_score || 0).toFixed(3)}</p>
                              <p className="metric-sub">Mean grounded confidence score.</p>
                            </div>
                          </>
                        )}
                      </div>
                      <div className="monitoring-panels">
                        <section className="monitor-panel wide">
                          <div className="monitor-panel-header">
                            <div>
                              <h3>Latency Breakdown</h3>
                              <p>Where response time is actually spent.</p>
                            </div>
                            <strong>{formatMetricMs(latencyTotal)}</strong>
                          </div>
                          <div className="latency-stack">
                            {latencyBreakdown.map((item) => (
                              <div
                                key={item.label}
                                className={`latency-segment ${item.tone}`}
                                style={{ width: `${latencyTotal > 0 ? (item.value / latencyTotal) * 100 : 0}%` }}
                                title={`${item.label}: ${formatMetricMs(item.value)}`}
                              />
                            ))}
                          </div>
                          <div className="latency-legend">
                            {latencyBreakdown.map((item) => (
                              <div key={item.label} className="latency-legend-item">
                                <span className={`legend-swatch ${item.tone}`} />
                                <span>{item.label}</span>
                                <strong>{formatMetricMs(item.value)}</strong>
                              </div>
                            ))}
                          </div>
                        </section>
                        <section className="monitor-panel wide">
                          <div className="monitor-panel-header">
                            <div>
                              <h3>Queries by Mode</h3>
                              <p>Distribution of workload across answer strategies.</p>
                            </div>
                            <strong>{totalQueries} total</strong>
                          </div>
                          <div className="mode-bars">
                            {queryModeEntries.length > 0 ? queryModeEntries.map(([m, count]) => (
                              <div key={m} className="mode-bar-row">
                                <div className="mode-bar-label">
                                  <span>{m.replace(/_/g, " ").toUpperCase()}</span>
                                  <strong>{count}</strong>
                                </div>
                                <div className="mode-bar-track">
                                  <div
                                    className="mode-bar-fill"
                                    style={{ width: `${totalQueries > 0 ? (count / totalQueries) * 100 : 0}%` }}
                                  />
                                </div>
                                <span className="mode-bar-share">
                                  {totalQueries > 0 ? ((count / totalQueries) * 100).toFixed(1) : "0.0"}%
                                </span>
                              </div>
                            )) : <p className="muted">No query data yet.</p>}
                          </div>
                        </section>
                        <section className="monitor-panel">
                          <div className="monitor-panel-header">
                            <div>
                              <h3>Error Hotspots</h3>
                              <p>Most common backend failure categories.</p>
                            </div>
                          </div>
                          <div className="error-list">
                            {topErrors.length > 0 ? topErrors.map((error) => (
                              <div key={error.error_type} className="error-list-item">
                                <span>{error.error_type}</span>
                                <strong>{error.count}</strong>
                              </div>
                            )) : <p className="muted">No errors recorded in this period.</p>}
                          </div>
                        </section>
                        <section className="monitor-panel">
                          <div className="monitor-panel-header">
                            <div>
                              <h3>Retrieval Quality Snapshot</h3>
                              <p>Quick read on coverage and trustworthiness.</p>
                            </div>
                          </div>
                          <div className="quality-stats">
                            <div className="quality-stat">
                              <span className="quality-label">Confidence</span>
                              <strong>{((metrics?.grounding?.avg_confidence_score || 0) * 100).toFixed(1)} / 100</strong>
                            </div>
                            <div className="quality-stat">
                              <span className="quality-label">Retrieved Chunks</span>
                              <strong>{metrics?.grounding?.avg_retrieved_chunks || 0}</strong>
                            </div>
                            <div className="quality-stat">
                              <span className="quality-label">Refusals</span>
                              <strong>{metrics?.grounding?.refusal_count || 0}</strong>
                            </div>
                            <div className="quality-stat">
                              <span className="quality-label">Low Evidence</span>
                              <strong>{metrics?.grounding?.insufficient_evidence_count || 0}</strong>
                            </div>
                          </div>
                        </section>
                      </div>
                    </div>
                  ) : <p>Loading metrics...</p>}
                </div>
              ) : messages.length === 0 ? (
                <div className="welcome-screen">
                  <h2>Welcome to your research workspace</h2>
                  <p>Upload scientific papers, select them as context, and ask questions with strict citation grounding.</p>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <div key={i} className={`message ${msg.role}`}>
                    <div className="message-content">
                      {msg.title && <h3 className="lit-review-title">{msg.title}</h3>}

                      {msg.comparison ? (
                        <div className="comparison-view">
                          <h4>{msg.text}</h4>
                          {msg.comparison.message && (
                            <p className="muted" style={{ marginBottom: "12px" }}>
                              {msg.comparison.message}
                            </p>
                          )}
                          {msg.comparison.claims?.map((c, idx) => (
                            <div key={idx} className="claim-card">
                              <p className="claim-text"><strong>Claim:</strong> {c.claim}</p>
                              <div className="papers-stances">
                                {c.papers?.map((p, pidx) => (
                                  <div key={pidx} className={`stance-badge ${p.stance}`}>
                                    <span>{p.paper_id.split('_').pop()}</span>: {p.stance}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="formatted-text">
                          {msg.reviewWarning && (
                            <div className={`review-alert ${msg.reviewStatus || "normal_review"}`}>
                              {msg.reviewWarning}
                            </div>
                          )}
                          {msg.text.split('\n').map((line, lidx) => (
                            <p key={lidx}>{line}</p>
                          ))}
                        </div>
                      )}

                      {msg.discoveryMode && (
                        <p className="message-mode-note">
                          {msg.discoveryMode.startsWith("external_search_answer")
                            ? `Answered from external paper discovery${msg.sourceBasis ? ` (${msg.sourceBasis.replace(/_/g, " ")})` : ""}.`
                            : msg.discoveryMode === "external_search_unavailable"
                              ? "External paper providers were temporarily unavailable or rate-limited."
                              : "No local context was selected, so the assistant abstained."}
                        </p>
                      )}

                      {msg.suggestedSources && msg.suggestedSources.length > 0 && (
                        <div className="suggested-sources">
                          {msg.suggestedSources.map((paper) => (
                            <div key={paper.id} className="suggested-paper">
                              <div>
                                <strong>{paper.title}</strong>
                                <p>{(paper.authors || []).slice(0, 4).join(", ") || "Unknown authors"}</p>
                              </div>
                              <div className="arxiv-actions">
                                {paper.url && (
                                  <a
                                    href={paper.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="arxiv-link-btn"
                                  >
                                    Open
                                  </a>
                                )}
                                <button
                                  className="mini-btn"
                                  onClick={() => importExternal(paper.id, paper.provider || "semanticscholar")}
                                >
                                  Import
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {msg.citations && msg.citations.length > 0 && (
                        <div className="citations-grid">
                          {msg.citations.map((c, j) => {
                            const isSelected = selectedCitations.some((item) => citationKey(item) === citationKey(c));
                            return (
                              <div
                                key={j}
                                className={`citation-chip clickable ${j === 0 ? "top-evidence" : ""} ${isSelected ? "selected" : ""}`}
                                onClick={() => openCitationViewer(c)}
                                title={c.snippet || "Open citation in PDF viewer"}
                              >
                                <span>View {c.source} (p.{Number(c.page || 0) + 1})</span>
                                {typeof c.score === "number" && (
                                  <span className="citation-score">{c.score.toFixed(3)}</span>
                                )}
                                {j === 0 && <span className="citation-best">Best</span>}
                                <button
                                  className="citation-select-btn"
                                  onClick={(e) => toggleCitationSelection(c, e)}
                                  title={isSelected ? "Remove selection" : "Select citation for highlights"}
                                >
                                  {isSelected ? "Selected" : "Select"}
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
              <div ref={chatEndRef} />
            </div>
          </div>

          {pdfViewer && (
            <div className={`pdf-drawer-shell ${isPdfDrawerResizing ? "resizing" : ""}`} style={{ "--pdf-drawer-width": `${pdfDrawerWidth}px` }}>
              <button
                type="button"
                className="pdf-drawer-resize-handle"
                onMouseDown={startPdfDrawerResize}
                aria-label="Resize PDF reader panel"
                title="Drag to resize PDF reader panel"
              />
              <div className="pdf-drawer">
              <div className="pdf-drawer-header">
                <div>
                  <strong>{pdfViewer.filename}</strong>
                  <p>Page {pdfViewer.page}</p>
                </div>
                <div className="pdf-drawer-actions">
                  <button
                    className="text-btn"
                    onClick={() => {
                      setPdfViewer(null);
                    }}
                  >
                    Close
                  </button>
                </div>
              </div>
              <div className="pdf-drawer-content">
                <div className="pdf-preview-column">
                  {pdfViewer.mode === "pdf" ? (
                    <iframe
                      title="PDF.js Viewer"
                      className="pdf-frame"
                      src={pdfViewer.viewerUrl}
                    />
                  ) : (
                    <div className="text-preview-panel">
                      <div className="text-preview-header">
                        <strong>Text Preview</strong>
                        <span className="muted">Metadata-only source</span>
                      </div>
                      <pre className="text-preview-content">
                        {pdfViewer.textPreview || pdfViewer.snippet || "No preview text available."}
                      </pre>
                    </div>
                  )}
                  <div className="drawer-section">
                    <div className="viewer-selection-header">
                      <div>
                        <h4>{pdfViewer.mode === "pdf" ? "Selectable Page Text" : "Selectable Document Text"}</h4>
                        <p className="muted">
                          Select a passage here to turn it into the active citation.
                        </p>
                      </div>
                      <div className="viewer-page-controls">
                        <button
                          type="button"
                          className="text-btn"
                          onClick={() => changePdfViewerPage(-1)}
                          disabled={Number(pdfViewer.page || 1) <= 1}
                        >
                          Prev
                        </button>
                        <span className="muted">Page {pdfViewer.page}{pdfViewer.pageCount ? ` / ${pdfViewer.pageCount}` : ""}</span>
                        <button
                          type="button"
                          className="text-btn"
                          onClick={() => changePdfViewerPage(1)}
                          disabled={Number(pdfViewer.page || 1) >= Number(pdfViewer.pageCount || 1)}
                        >
                          Next
                        </button>
                      </div>
                    </div>
                    <div className="selectable-text-panel" ref={selectableTextRef} onMouseUp={captureViewerSelection}>
                      <pre className="text-preview-content selectable-text-content">
                        {pdfViewer.textPreview || "No extracted text available for this page."}
                      </pre>
                    </div>
                  </div>
                </div>

                <div className="pdf-notes-column">
                  <div className="drawer-section drawer-section-first">
                    <h4>Citation Snippet</h4>
                    <p className="snippet-box">{pdfViewer.snippet || "Select text from the panel above to create a citation snippet."}</p>
                    {pdfViewer.precisePhrase && pdfViewer.snippet && (
                      <p className="muted" style={{ marginTop: "6px" }}>
                        Precise page phrase: "{pdfViewer.precisePhrase}"
                      </p>
                    )}
                  </div>
                  <div className="drawer-section">
                    <h4>Create Highlight</h4>
                    <input
                      type="text"
                      value={highlightNote}
                      onChange={(e) => setHighlightNote(e.target.value)}
                      placeholder="Optional note..."
                    />
                    <input
                      type="text"
                      value={highlightTags}
                      onChange={(e) => setHighlightTags(e.target.value)}
                      placeholder="Tags (comma-separated)"
                    />
                    <button className="btn-primary" onClick={createHighlightFromCitation}>
                      Save Highlight
                    </button>
                  </div>

                  <div className="drawer-section">
                    <h4>Highlights In This Document</h4>
                    <div className="highlight-list">
                      {highlights.map((hl) => (
                        <div key={hl.id} className="highlight-item">
                          <div className="highlight-row">
                            <span>p.{hl.page}</span>
                            <button className="text-btn" onClick={() => deleteHighlight(hl.id)}>
                              Delete
                            </button>
                          </div>
                          <p>{hl.text}</p>
                          {hl.note && <p className="muted">Note: {hl.note}</p>}
                        </div>
                      ))}
                      {highlights.length === 0 && <p className="muted">No highlights yet.</p>}
                    </div>
                  </div>

                  <div className="drawer-section">
                    <h4>Search In My Highlights (Session)</h4>
                    <form className="input-group" onSubmit={searchMyHighlights}>
                      <input
                        type="text"
                        value={highlightSearch}
                        onChange={(e) => setHighlightSearch(e.target.value)}
                        placeholder='e.g. supporting evidence for "claim X"'
                      />
                      <button className="btn-icon" type="submit">Go</button>
                    </form>
                    {highlightSearchLoading && <p className="muted">Searching highlights...</p>}
                    <div className="highlight-list">
                      {highlightSearchResults.map((hl) => (
                        <button
                          key={`${hl.id}-${hl.score}`}
                          className="highlight-search-hit"
                          onClick={() =>
                            openCitationViewer({
                              source: hl.filename,
                              page: hl.page || 1,
                              snippet: hl.text,
                              pageOneIndexed: true,
                            })
                          }
                        >
                          <strong>{hl.filename}</strong> p.{hl.page} ({(hl.score || 0).toFixed(3)})
                          <p>{hl.text}</p>
                        </button>
                      ))}
                      {highlightSearchResults.length === 0 && <p className="muted">No search results yet.</p>}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            </div>
          )}
        </div>

        {mode !== 'monitoring' && (
          <div className="input-area">
            {loading && <div className="thinking-banner">Model is thinking. The question bar is temporarily locked.</div>}
            {status && <div className="status-indicator">{status}</div>}
            {selectedCitations.length > 0 && (
              <div className="selected-citations-bar">
                <strong>{selectedCitations.length} citation{selectedCitations.length > 1 ? "s" : ""} selected</strong>
                <input
                  type="text"
                  value={selectedCitationNote}
                  onChange={(e) => setSelectedCitationNote(e.target.value)}
                  placeholder="Optional note for selected citations..."
                />
                <input
                  type="text"
                  value={selectedCitationTags}
                  onChange={(e) => setSelectedCitationTags(e.target.value)}
                  placeholder="Tags (comma-separated)"
                />
                <button className="btn-primary compact" type="button" onClick={saveSelectedCitationsAsHighlights}>
                  Save Selected Citations
                </button>
                <button className="text-btn" type="button" onClick={() => setSelectedCitations([])}>
                  Clear Selection
                </button>
              </div>
            )}
            <form onSubmit={askQuestion} className={`chat-input-wrapper ${loading ? "blocked" : ""}`}>
              <input
                type="text"
                placeholder={
                  distinctSelectedCount >= activeModeConfig.minSources
                    ? `Ask a question in ${activeModeConfig.label} mode...`
                    : mode === "lit_review"
                      ? "Select at least 2 papers for a literature review"
                      : mode === "compare"
                        ? "Select at least 2 papers to compare"
                        : "Select a source to start asking questions"
                }
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={loading}
              />
              <button
                type="submit"
                className="btn-icon"
                disabled={loading || !question.trim() || distinctSelectedCount < activeModeConfig.minSources}
              >
                Send
              </button>
            </form>
            <div className="prompt-toolbar">
              <div className="mode-selector compact">
                {['qa', 'compare', 'lit_review', 'monitoring'].map((m) => {
                  const config = MODE_CONFIG[m];
                  const minSourcesHint = config.minSources > 1 ? ` Requires at least ${config.minSources} sources.` : "";
                  return (
                    <button
                      key={m}
                      type="button"
                      className={`mode-btn compact ${mode === m ? 'active' : ''}`}
                      onClick={() => setMode(m)}
                      title={`${config.label}: ${config.description}${minSourcesHint}`}
                      aria-label={`${config.label}. ${config.description}${minSourcesHint}`}
                    >
                      {config.label}
                    </button>
                  );
                })}
              </div>
              <div className="prompt-actions">
                <button
                  type="button"
                  className={`text-btn inline-action ${isHighlightSearchOpen ? "active" : ""}`}
                  onClick={() => setIsHighlightSearchOpen((open) => !open)}
                >
                  Highlights
                </button>
              </div>
            </div>
            {isHighlightSearchOpen && (
              <div className="highlight-search-inline">
                <div className="highlight-panel-tabs">
                  <button
                    type="button"
                    className={`source-tab ${highlightPanelView === "search" ? "active" : ""}`}
                    onClick={() => setHighlightPanelView("search")}
                  >
                    Search
                  </button>
                  <button
                    type="button"
                    className={`source-tab ${highlightPanelView === "saved" ? "active" : ""}`}
                    onClick={() => setHighlightPanelView("saved")}
                  >
                    All Saved
                  </button>
                </div>
                {highlightPanelView === "search" ? (
                  <>
                    <form className="input-group compact" onSubmit={searchMyHighlights}>
                      <input
                        type="text"
                        value={highlightSearch}
                        onChange={(e) => setHighlightSearch(e.target.value)}
                        placeholder='Search saved highlights (e.g. "supporting evidence for claim X")'
                      />
                      <button className="btn-icon" type="submit">Go</button>
                    </form>
                    {highlightSearchLoading && <p className="muted">Searching highlights...</p>}
                    {highlightSearchResults.length > 0 && (
                      <div className="global-highlight-results compact">
                        {highlightSearchResults.slice(0, 5).map((hl) => (
                          <button
                            key={`global-${hl.id}-${hl.score}`}
                            className="highlight-search-hit"
                            onClick={() =>
                              openCitationViewer({
                                source: hl.filename,
                                page: hl.page || 1,
                                snippet: hl.text,
                                pageOneIndexed: true,
                              })
                            }
                          >
                            <strong>{hl.filename}</strong> p.{hl.page} ({(hl.score || 0).toFixed(3)})
                            <p>{hl.text}</p>
                          </button>
                        ))}
                      </div>
                    )}
                    {!highlightSearchLoading && highlightSearch.trim() && highlightSearchResults.length === 0 && (
                      <p className="muted">No matching highlights.</p>
                    )}
                  </>
                ) : (
                  <div className="highlight-library">
                    {allHighlightsLoading ? (
                      <p className="muted">Loading saved highlights...</p>
                    ) : allHighlights.length > 0 ? (
                      Object.entries(
                        allHighlights.reduce((groups, hl) => {
                          const key = hl.filename || "Unknown source";
                          if (!groups[key]) groups[key] = [];
                          groups[key].push(hl);
                          return groups;
                        }, {})
                      ).map(([filename, entries]) => (
                        <div key={filename} className="highlight-library-group">
                          <div className="highlight-library-header">
                            <strong>{filename}</strong>
                            <span>{entries.length} highlight{entries.length > 1 ? "s" : ""}</span>
                          </div>
                          <div className="highlight-list">
                            {entries.map((hl) => (
                              <div key={`saved-${hl.id}`} className="highlight-library-card">
                                <div className="highlight-library-card-header">
                                  <strong>p.{hl.page}</strong>
                                  <div className="highlight-library-card-actions">
                                    <button
                                      type="button"
                                      className="text-btn"
                                      onClick={() =>
                                        openCitationViewer({
                                          source: hl.filename,
                                          page: hl.page || 1,
                                          snippet: hl.text,
                                          pageOneIndexed: true,
                                        })
                                      }
                                    >
                                      Open
                                    </button>
                                    <button
                                      type="button"
                                      className="text-btn"
                                      onClick={() => deleteHighlight(hl.id)}
                                    >
                                      Delete
                                    </button>
                                  </div>
                                </div>
                                <p>{hl.text}</p>
                                {hl.note && <p className="muted">Note: {hl.note}</p>}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="muted">No saved highlights yet.</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
