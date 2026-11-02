"""Load supported documents and preserve page-level citation metadata."""
from pathlib import Path
import math
import re
from zipfile import ZipFile
from xml.etree import ElementTree

from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def load_documents(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    elif suffix == ".docx":
        with ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 40 * 1024 * 1024:
                raise ValueError("Word 文档解压后过大，请拆分文件。")
            root = ElementTree.fromstring(archive.read(info))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = ["".join(p.itertext()) for p in root.findall(".//w:p", ns)]
        docs = [Document(page_content="\n".join(paragraphs))]
    elif suffix in {".txt", ".md"}:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                docs = [Document(page_content=path.read_text(encoding=encoding))]
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法识别文本编码，请将文件另存为 UTF-8。")
    else:
        raise ValueError("支持 PDF、Word、TXT 和 Markdown 文件。")
    return docs


def load_chunks(path: Path):
    docs = load_documents(path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=512, chunk_overlap=64,
        separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""])
    return [doc for doc in splitter.split_documents(docs) if doc.page_content.strip()]


def load_semantic_chunks(path, embeddings, threshold=0.55):
    """Group adjacent sentences by embedding similarity, retaining page boundaries."""
    result = []
    for doc in load_documents(path):
        sentences = [s for s in re.split(r"(?<=[。！？!?\n])|(?<=\.)\s+", doc.page_content) if s.strip()]
        units = [sentence[i:i + 512] for sentence in sentences for i in range(0, len(sentence), 512)]
        if not units:
            continue
        vectors = embeddings.embed_documents(units)
        current = units[0]
        for i in range(1, len(units)):
            a, b = vectors[i - 1], vectors[i]
            denom = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
            similarity = sum(x*y for x, y in zip(a, b)) / denom if denom else 0
            if len(current) + len(units[i]) > 512 or similarity < threshold:
                result.append(Document(page_content=current, metadata=dict(doc.metadata)))
                current = units[i]
            else:
                current += units[i]
        result.append(Document(page_content=current, metadata=dict(doc.metadata)))
    return result
