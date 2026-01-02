# Resume RAG Chatbot (FAISS + Gemini)

A local Flask web app that:
- Lets you upload a resume (PDF/DOCX/TXT)
- Embeds and indexes it with FAISS
- Uses Google Gemini to generate interview questions based on the resume

## Setup

```bash
git clone <your-repo>
cd rag_chatbot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
