import os
import io
import uuid
import json
import time
import threading
from pathlib import Path
from flask import Flask, request, render_template, jsonify
from flask_cors import CORS
import numpy as np
import sys
import re

# -------------------------------------------------------------------
# PDF/DOCX processing
# -------------------------------------------------------------------
try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

try:
    import docx
except ImportError:
    docx = None

# FAISS for vector storage
try:
    import faiss
except ImportError:
    faiss = None

# Gemini AI
import google.generativeai as genai

# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------
API_KEY_PATH = Path("config/api_key.txt")

if not API_KEY_PATH.exists():
    raise FileNotFoundError("API key file 'api_key.txt' not found. Please create it and add your Gemini API key.")

GEMINI_API_KEY = API_KEY_PATH.read_text(encoding="utf-8").strip()
genai.configure(api_key=GEMINI_API_KEY)

EMBED_MODEL = "models/text-embedding-004"
GEN_MODEL = "gemini-2.5-flash"


DATA_DIR = Path("./data")
DATA_DIR.mkdir(exist_ok=True)
FAISS_INDEX_PATH = DATA_DIR / "resume_index.faiss"
META_PATH = DATA_DIR / "resume_meta.json"

# Global state
EMBED_DIM = 768
meta = {}
index = None
processing_status = {}
lock = threading.Lock()

# -------------------------------------------------------------------
# TEXT EXTRACTION
# -------------------------------------------------------------------
def extract_text_from_pdf(file_bytes):
    if PdfReader is None:
        raise ImportError("PyPDF2 not installed")
    reader = PdfReader(io.BytesIO(file_bytes))
    text = []
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text.append(extracted)
    return "\n".join(text)

def extract_text_from_docx(file_bytes):
    if docx is None:
        raise ImportError("python-docx not installed")
    temp_path = DATA_DIR / "temp_upload.docx"
    with open(temp_path, "wb") as f:
        f.write(file_bytes)
    doc = docx.Document(temp_path)
    text = "\n".join([p.text for p in doc.paragraphs])
    temp_path.unlink()
    return text

def extract_text(file_bytes, filename):
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext == "docx":
        return extract_text_from_docx(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {ext}")

# -------------------------------------------------------------------
# TEXT CHUNKING
# -------------------------------------------------------------------
def simple_sentence_split(text):
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]

def chunk_text(text, chunk_size=600, overlap=100):
    sentences = simple_sentence_split(text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += " " + sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())

    overlapped_chunks = []
    for i, chunk in enumerate(chunks):
        if i > 0 and overlap > 0:
            prev_chunk = chunks[i - 1]
            overlap_text = prev_chunk[-overlap:] if len(prev_chunk) > overlap else prev_chunk
            chunk = overlap_text + " " + chunk
        overlapped_chunks.append(chunk)
    return [c for c in overlapped_chunks if len(c) > 30]

# -------------------------------------------------------------------
# EMBEDDING & FAISS
# -------------------------------------------------------------------
def embed_text(text):
    try:
        text = text.strip()
        if len(text) < 10:
            print(f"Warning: text too short for embedding ({len(text)} chars)")
            return None
        if len(text) > 10000:
            text = text[:10000]
            print("Warning: text truncated to 10000 characters")

        result = genai.embed_content(model=EMBED_MODEL, content=text, task_type="retrieval_document")
        if "embedding" not in result:
            print("Error: no embedding returned")
            return None

        vec = np.array(result["embedding"], dtype=np.float32)
        if len(vec) == 0:
            print("Error: empty embedding vector")
            return None

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    except Exception as e:
        print(f"Embedding error: {e}")
        return None

def ensure_index():
    global index
    with lock:
        if index is None:
            if faiss is None:
                raise ImportError("FAISS not installed")
            if FAISS_INDEX_PATH.exists():
                try:
                    loaded_index = faiss.read_index(str(FAISS_INDEX_PATH))
                    index = loaded_index
                    print(f"Loaded existing FAISS index with {index.ntotal} vectors.")
                    return
                except Exception as e:
                    print(f"Could not load existing index: {e}")
            index = faiss.IndexFlatIP(EMBED_DIM)
            print("Created new FAISS index.")

def save_index():
    try:
        with lock:
            if index is not None:
                faiss.write_index(index, str(FAISS_INDEX_PATH))
            with open(META_PATH, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        print("Index and metadata saved.")
    except Exception as e:
        print(f"Save error: {e}")

# -------------------------------------------------------------------
# BACKGROUND PROCESSING
# -------------------------------------------------------------------
def process_resume_background(resume_id, text):
    try:
        print(f"Processing resume {resume_id}...")
        processing_status[resume_id] = "processing"

        chunks = chunk_text(text)
        if not chunks:
            processing_status[resume_id] = "error: no valid chunks"
            print("No valid chunks created.")
            return

        print(f"Created {len(chunks)} chunks.")
        ensure_index()

        vectors, valid_chunks = [], []
        print("Embedding chunks...")
        for i, chunk in enumerate(chunks):
            vec = embed_text(chunk)
            if vec is not None:
                vectors.append(vec)
                valid_chunks.append(chunk)
                print(f"Embedded chunk {i + 1}/{len(chunks)}")
            else:
                print(f"Failed to embed chunk {i + 1}")
            time.sleep(0.15)

        if not vectors:
            processing_status[resume_id] = "error: all embeddings failed"
            print("All embeddings failed.")
            return

        vec_array = np.vstack(vectors).astype(np.float32)
        with lock:
            if index is None:
                ensure_index()
            start_idx = index.ntotal
            print(f"Adding {len(vectors)} vectors to index (current total: {start_idx})")
            index.add(vec_array)
            for i, chunk in enumerate(valid_chunks):
                vec_id = str(start_idx + i)
                meta[vec_id] = {"resume_id": resume_id, "chunk": chunk}
            print(f"Index now has {index.ntotal} vectors.")

        save_index()
        processing_status[resume_id] = "done"
        print(f"Resume {resume_id} processed successfully.")

    except Exception as e:
        processing_status[resume_id] = f"error: {str(e)}"
        print(f"Processing error: {e}")

# -------------------------------------------------------------------
# FLASK APP
# -------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app, resources={r"/*": {"origins": "*"}})
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "index_initialized": index is not None,
        "vectors_count": index.ntotal if index else 0,
        "metadata_count": len(meta),
    })

@app.route("/upload", methods=["POST"])
def upload_resume():
    try:
        print("Received upload request.")
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        print(f"Processing file: {file.filename}")
        file_bytes = file.read()
        print(f"File size: {len(file_bytes)} bytes")

        text = extract_text(file_bytes, file.filename)
        print(f"Extracted text length: {len(text)} characters")

        if len(text.strip()) < 50:
            return jsonify({"error": "Resume text too short"}), 400

        resume_id = str(uuid.uuid4())
        text_path = DATA_DIR / f"{resume_id}.txt"
        text_path.write_text(text, encoding="utf-8")
        print(f"Saved text to: {text_path}")

        processing_status[resume_id] = "queued"
        thread = threading.Thread(target=process_resume_background, args=(resume_id, text), daemon=True)
        thread.start()
        print("Started background processing.")

        return jsonify({
            "success": True,
            "resume_id": resume_id,
            "status": "queued",
            "message": "Resume uploaded successfully. Processing..."
        }), 200

    except Exception as e:
        print(f"Upload error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/status/<resume_id>")
def check_status(resume_id):
    status_val = processing_status.get(resume_id, "not_found")
    return jsonify({"resume_id": resume_id, "status": status_val})

@app.route("/generate", methods=["POST"])
def generate_questions():
    try:
        data = request.get_json() or {}
        resume_id = data.get("resume_id")
        num_questions = int(data.get("count", 5))

        if not resume_id:
            return jsonify({"error": "resume_id required"}), 400
        status_val = processing_status.get(resume_id)
        if status_val != "done":
            return jsonify({"error": f"Resume not ready. Status: {status_val}"}), 400

        chunks = [m["chunk"] for m in meta.values() if m.get("resume_id") == resume_id]
        if not chunks:
            return jsonify({"error": "No resume data found"}), 400

        context = "\n\n".join(chunks[:5])
        prompt = f"""You are an expert technical interviewer. Based on the following resume excerpt, generate {num_questions} diverse and relevant interview questions.

Return ONLY valid JSON in this exact format:
{{
  "questions": [
    {{"type": "technical", "difficulty": "medium", "question": "Your question here"}}
  ]
}}

Resume excerpt:
{context[:2000]}

Generate {num_questions} questions now:"""

        model = genai.GenerativeModel(GEN_MODEL)
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        result = json.loads(response_text)
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({
            "questions": [
                {"type": "general", "difficulty": "medium", "question": "Tell me about your experience and background."}
            ]
        })
    except Exception as e:
        print(f"Generation error: {e}")
        return jsonify({"error": str(e)}), 500

# -------------------------------------------------------------------
# STARTUP
# -------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 50)
    print("Resume Interview Question Generator (No Emoji)")
    print("=" * 50)

    if META_PATH.exists():
        try:
            with open(META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            print(f"Loaded {len(meta)} metadata entries.")
        except Exception as e:
            print(f"Could not load metadata: {e}")
            meta = {}

    try:
        if FAISS_INDEX_PATH.exists():
            index = faiss.read_index(str(FAISS_INDEX_PATH))
            print(f"Loaded FAISS index with {index.ntotal} vectors.")
        else:
            print("Creating new FAISS index.")
            index = faiss.IndexFlatIP(EMBED_DIM)
    except Exception as e:
        print(f"Index initialization error: {e}")
        index = None

    print("Server starting on http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
