#!/usr/bin/python3
"""
Web based ChatBot - Documents Handling Module

This module is responsible for ingesting and managing documents in the
vector database, weaviate. It uses the Weaviate Python client to interact
with the weaviate instance.

Class Documents:
    create: Create a collection in weaviate
    delete: Delete a collection in weaviate
    connect: Connect to the weaviate instance
    close: Close the weaviate connection
    all_collections: List all collections in weaviate
    list_documents: List all documents in collection with file as the key
    get_document: Get a document by its ID
    get_documents: Get a document by ID or query
    delete_document: Delete a document by its ID
    add_document: Ingest a document into weaviate
    update_document: Update a document in weaviate by its ID
    set_max_chunk_size: Set the maximum chunk size for document content
    add_file: Detect and convert document, filename argument
    add_url: Import URL document
    add_pdf: Add a PDF document
    add_docx: Add a DOCX document
    add_txt: Add a TXT document

Requirements:
    !pip install weaviate-client pdfreader bs4 pypandoc pypdf requests

Run Test:
    WEAVIATE_HOST=localhost python3 documents.py

Author: Jason A. Cox
16 September 2024
https://github.com/jasonacox/TinyLLM

"""

# Imports
import os
import io
import logging
import time

import weaviate.classes as wvc
import weaviate
from weaviate.exceptions import WeaviateConnectionError
from weaviate.classes.query import Filter
import requests
from pypdf import PdfReader
from bs4 import BeautifulSoup
import pypandoc

# optional - download pandoc
#from pypandoc.pandoc_download import download_pandoc
#download_pandoc()

# Logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

def log(msg):
    logger.debug(msg)

# Defaults
MAX_CHUNK_SIZE=256*4

# Document class
class Documents:
    """
    Documents class

    The Document class is responsible for managing documents in the vector
    database, weaviate. It uses the Weaviate Python client to interact with
    the weaviate instance.

    Attributes:
        client: Weaviate client object
    """

    def __init__(self, host="localhost", filepath="/tmp", port=8080, grpc_port=50051, retry=3):
        """
        Initialize the Document class
        """
        # Weaviate client object
        self.host = host                        # Weaviate host IP address
        self.filepath = filepath                # File path for temporary document storage
        self.port = port                        # Weaviate port
        self.grpc_port = grpc_port              # Weaviate gRPC port
        self.client = None                      # Weaviate client object
        self.retry = retry                      # Number of times to retry connection
        self.max_chunk_size = MAX_CHUNK_SIZE    # Maximum chunk size for document content
        # Verify file path
        if not os.path.exists(filepath):
            raise Exception('File path does not exist')

    def connect(self):
        """
        Connect to the weaviate instance
        """
        x = self.retry
        # Connect to Weaviate
        while x:
            try:
                self.client = weaviate.connect_to_local(
                    host=self.host,
                    port=self.port,
                    grpc_port=self.grpc_port,
                    additional_config=weaviate.config.AdditionalConfig(timeout=(15, 115))
                )
                log(f"Connected to Weaviate at {self.host}")
                return True
            except WeaviateConnectionError as er:
                log(f"Connection error: {str(er)}")
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError(f"Unable to connect to Weaviate at {self.host}")
        return False

    def close(self):
        """
        Close the weaviate connection
        """
        if self.client:
            self.client.close()
            log("Connection to Weaviate closed")
            self.client = None

    def set_max_chunk_size(self, size):
        """
        Set the maximum chunk size for document content
        """
        self.max_chunk_size = size
        
    def all_collections(self):
        """
        List all collections in weaviate

        Returns:
            collections: List of collections
        """
        if not self.client:
            self.connect()
        x = self.retry
        while x:
            try:
                c = []
                collections = self.client.collections.list_all(simple=True)
                for i in collections:
                    c.append(i)
                log(f"Collections: {c}")
                break
            except WeaviateConnectionError as er:
                log(f"Connection error: {str(er)}")
                self.connect()
                time.sleep(1)
                x -= 1
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return c

    def create(self, collection):
        """
        Create a collection in weaviate
        """
        x = self.retry
        if not self.client:
            self.connect()
        # Verify it does not exist
        collections = self.all_collections()
        if collection.title() in collections:
            log(f"Collection already exists: {collection}")
            return False
        # Create a collection
        while x: # retry until success
            try:
                self.client.collections.create(
                    name=collection,
                    vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_transformers()
                )
                log(f"Collection created: {collection}")
                break
            except WeaviateConnectionError as er:
                log(f"Connection error: {str(er)}")
                self.connect()
                time.sleep(1)
                x -= 1
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return True

    def delete(self, collection):
        """
        Delete a collection in weaviate
        """
        x = self.retry
        if not self.client:
            self.connect()
        # Verify it does not exist
        collections = self.all_collections()
        if not collection.title() in collections:
            log(f"Collection does not exist: {collection}")
            return False
        # Delete a collection
        while x:
            try:
                self.client.collections.delete(collection)
                log(f"Collection deleted: {collection}")
                break
            except WeaviateConnectionError as er:
                log(f"Connection error: {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return True

    def list_documents(self, collection=None):
        """
        List all documents in collection with file as the key

        Returns:
            documents: Dictionary of documents with filename as the key
            {
                "filename.txt": {
                    "uuid": {
                        "title": "title", 
                        "doc_type": "doc_type"
                    }
                }
            }
        """
        x = self.retry
        documents = {}
        # List all documents in collection
        if not self.client:
            self.connect()
        # Get list of documents in collection
        while x:
            try:
                collection = self.client.collections.get(collection)
                for o in collection.iterator():
                    p = o.properties
                    uuid = str(o.uuid)
                    filename = p.get("file")
                    title = p.get("title")
                    doc_type = p.get("doc_type")
                    creation_time = p.get("creation_time")
                    if filename not in documents:
                        documents[filename] = {}
                    documents[filename][uuid] = {
                        "title": title,
                        "doc_type": doc_type,    
                        "creation_time": creation_time            
                    }
                break
            except WeaviateConnectionError as er:
                log(f"Connection error: {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return documents

    def get_document(self, collection, uuid):
        """
        Return a document by its ID
        """
        document = None
        x = self.retry
        if not self.client:
            self.connect()
        # Get a document by its ID - list fist element if list
        while x:
            try:
                c = self.client.collections.get(collection)
                udocs = c.query.fetch_objects(
                    filters=Filter.by_id().equal(uuid),
                )
                p = udocs.objects[0].properties
                document ={
                    "uuid": uuid,
                    "file": p.get("file"),
                    "title": p.get("title"),
                    "chunk": p.get("chunk"),
                    "doc_type": p.get("doc_type"),
                    "content": p.get("content"),
                    "creation_time": p.get("creation_time"),
                }
                break
            except WeaviateConnectionError as er:
                log(f"Connection error (retry {x}): {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return document

    def get_documents(self, collection, uuid=None, query=None, filename=None, num_results=10):
        """
        Return a document by ID, query or filename
        """
        dd = []
        x = self.retry
        if not self.client:
            self.connect()
        if uuid:
            # Get a document by its ID
            dd = [self.get_document(collection, uuid)]
        if query:
            # Search by vector query
            while x:
                try:
                    qdocs = self.client.collections.get(collection)
                    r = qdocs.query.near_text(
                        query=query,
                        limit=num_results
                    )
                    for i in r.objects:
                        p = i.properties
                        uuid = str(i.uuid)
                        dd.append( {
                            "uuid": uuid,
                            "file": p.get("file"),
                            "title": p.get("title"),
                            "chunk": p.get("chunk"),
                            "doc_type": p.get("doc_type"),
                            "content": p.get("content"),
                            "creation_time": p.get("creation_time"),
                        })
                    break
                except WeaviateConnectionError as er:
                    log(f"Connection error (retry {x}): {str(er)}")
                    self.connect()
                    x -= 1
                    time.sleep(1)
            if not x:
                raise WeaviateConnectionError("Unable to connect to Weaviate")
        if filename:
            # Get a document by its filename
            r = self.list_documents(collection)
            for fn in r:
                if fn == filename:
                    for uuid in r[fn]:
                        dd.append(self.get_document(collection, uuid))
        return dd

    def delete_document(self, collection, uuid=None, filename=None):
        """
        Delete a document by its ID or filename
        """
        r = None
        x = self.retry
        # Delete a document by its ID
        if not self.client:
            self.connect()
        while x:
            try:
                c = self.client.collections.get(collection)
                if uuid:
                    r = c.data.delete_by_id(uuid)
                    log(f"Document deleted: {uuid}")
                elif filename:
                    # Delete a document by its filename
                    documents = self.list_documents(collection)
                    for f in documents:
                        if f == filename:
                            # delete all UUIDs for this filename
                            for u in documents[f]:
                                r = c.data.delete_by_id(u)
                                log(f"Document deleted: {filename} - uuid: {u}")
                else:
                    raise ValueError('Missing document ID or filename')
                break
            except WeaviateConnectionError as er:
                log(f"Connection error (retry {x}): {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return r

    def add_document(self, collection, title, doc_type, filename, chunk=None, content=None):
        """
        Add a document into weaviate

        Inputs:
            collection: Collection name
            title: Document title
            doc_type: Document type
            filename: Document filename
            chunk: Document chunk - Part of the document
            content: Document content - Full text of the document
        """
        r = None
        dd = []
        if not chunk and not content:
            raise ValueError('Missing document content')
        if not content:
            content = chunk
        if not (title and doc_type and filename and content):
            raise ValueError('Missing document properties')
        if not chunk and self.max_chunk_size > 0:
            # Auto break up content into chunks
            chunks = break_up_content(content, self.max_chunk_size)
            ci = 0
            total_chunks = len(chunks)
            for chunk in chunks:
                ci = ci + 1
                if total_chunks > 1:
                    suffix = f" - Section {ci} of {total_chunks}"
                else:
                    suffix = ""
                dd.append({
                    "title": title + suffix,
                    "chunk": chunk,
                    "doc_type": doc_type,
                    "file": filename,
                    "content": content,
                    "creation_time": time.time()
                })
        else :
            dd.append({
                "title": title,
                "chunk": chunk,
                "doc_type": doc_type,
                "file": filename,
                "content": content,
                "creation_time": time.time()
            })
        x = self.retry
        if not self.client:
            self.connect()
        while x:
            try:
                c = self.client.collections.get(collection)
                r = c.data.insert_many(dd)
                log(f"Document added: {filename}")
                break
            except WeaviateConnectionError as er:
                log(f"Connection error (retry {x}): {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return r

    def update_document(self, collection, uuid, title, doc_type, filename, chunk=None, content=None):
        """
        Update a document in weaviate by its ID
        """
        # Delete and re-add document
        x = self.retry
        r = None
        if not self.client:
            self.connect()
        while x:
            try:
                self.delete_document(collection, uuid)
                r = self.add_document(collection, title, doc_type, filename, chunk, content)
                log(f"Document updated: {uuid}")
                break
            except WeaviateConnectionError as er:
                log(f"Connection error (retry {x}): {str(er)}")
                self.connect()
                x -= 1
                time.sleep(1)
        if not x:
            raise WeaviateConnectionError("Unable to connect to Weaviate")
        return r

    def add_file(self, collection, title, filename, tmp_file=None):
        """
        Detect and convert document into weaviate
        """
        # is filename a URL?
        if filename.startswith("http"):
            # TODO: Break into chunks
            return self.add_url(collection, title, filename)
        else:
            # Detect what type of file (case insensitive)
            if filename.lower().endswith('.pdf'):
                # PDF document
                return self.add_pdf(collection, title, filename, tmp_file)
            elif filename.lower().endswith('.docx'):
                # DOCX document
                return self.add_docx(collection, title, filename, tmp_file)
            elif filename.lower().endswith('.txt'):
                # TXT document
                return self.add_txt(collection, title, filename, tmp_file)
            elif filename.lower().endswith('.html'):
                # HTML document
                return self.add_html(collection, title, filename, tmp_file)
            elif filename.lower().endswith('.json'):
                # JSON document
                return self.add_json(collection, title, filename, tmp_file)
            else:
                # Unsupported document
                raise ValueError('Unsupported document format')

    def add_url(self, collection, title, url):
        """
        Import URL document
        """
        content = extract_from_url(url)
        if content:
            return self.add_document(collection, title, "URL", url, content=content)
        return None

    def add_pdf(self, collection, title, filename, tmp_file):
        """
        Add a PDF document from a local file
        """
        # Convert PDF to text document
        with open(tmp_file, 'rb') as file:
            pdf_content = file.read()
        pdf2text = ""
        pdf_file = io.BytesIO(pdf_content)
        reader = PdfReader(pdf_file)
        for page in reader.pages:
            pdf2text = page.extract_text() + "\n"
            # TODO: Break into chunks
            section = title + " - Page " + str(page.page_number+1)
            r = self.add_document(collection, section, "PDF", filename, content=pdf2text)
        return r

    def add_docx(self, collection, title, filename, tmp_file):
        """
        Add a DOCX document
        """
        # Convert DOCX file to text document
        docx2text = pypandoc.convert_file(tmp_file, 'plain', format='docx')
        # TODO: Break into chunks
        r = self.add_document(collection, title, "DOCX", filename, content=docx2text)
        return r

    def add_txt(self, collection, title, filename, tmp_file):
        """
        Add a TXT document
        """
        # Read text from TXT file
        with open(tmp_file, 'r') as f:
            txt2text = f.read()
        r = self.add_document(collection, title, "TXT", filename, content=txt2text)
        return r
    
    def add_html(self, collection, title, filename, tmp_file):
        """
        Add a HTML document
        """
        # Read and convert html to text
        with open(tmp_file, 'r') as f:
            html2text = f.read()
        soup = BeautifulSoup(html2text, 'html.parser')
        title = soup.title.string
        paragraphs = soup.find_all(['p', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'ol'])
        website_text = f"Document Title: {title}\nDocument Content:\n" + '\n\n'.join([p.get_text() for p in paragraphs])
        r = self.add_document(collection, title, "HTML", filename, content=website_text)
        return r
    
    def add_json(self, collection, title, filename, tmp_file):
        """
        Add a JSON document
        """
        # Read text from JSON file
        with open(tmp_file, 'r') as f:
            json2text = f.read()
        r = self.add_document(collection, title, "JSON", filename, content=json2text)
        return r
    

# End of document class

# Utility functions

# Function to break up content into chunks
def break_up_content(text, max_size):
    """Break up text into chunks of max_size."""
    if len(text) > max_size:
        # Break up text into lines and then into chunks
        lines = text.splitlines()
        result = []
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) > max_size:
                result.append(current_chunk)
                current_chunk = ""
            current_chunk = current_chunk + line + "\n"
        result.append(current_chunk)
        return result
    return [text]

def extract_from_url(url):
    """
    Extract text from a URL and return the content
    """
    # Function - Extract text from PDF
    def extract_text_from_pdf(response):
        # Convert PDF to text
        pdf_content = response.read
        pdf2text = ""
        pdf_f = io.BytesIO(pdf_content)
        reader = PdfReader(pdf_f)
        for page in reader.pages:
            pdf2text = pdf2text + page.extract_text() + "\n"
        pdf_f.close()
        return pdf2text

    # Function - Extract text from text
    def extract_text_from_text(response):
        return response.text

    # Function - Extract text from HTML
    def extract_text_from_html(response):
        html_content = response.text
        # get title of page from html
        source = "Document Source: " + str(response.url)
        soup = BeautifulSoup(html_content, 'html.parser')
        title = ("Document Title: " + soup.title.string + "\n") if soup.title else ""
        paragraphs = soup.find_all(['p', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'ol'])
        website_text = f"{title}{source}\nDocument Content:\n" + '\n\n'.join([p.get_text() for p in paragraphs])
        return website_text

    with requests.Session() as session:
        response = session.get(url, allow_redirects=True)
        if response.status_code == 200:
            # Route extraction based on content type
            if ";" in response.headers["Content-Type"]:
                content_type = response.headers["Content-Type"].split(";")[0]
            else:
                content_type = response.headers["Content-Type"]
            content_handlers = {
                "application/pdf": extract_text_from_pdf,
                "text/plain": extract_text_from_text,
                "text/csv": extract_text_from_text,
                "text/xml": extract_text_from_text,
                "application/json": extract_text_from_text,
                "text/html": extract_text_from_html,
                "application/xml": extract_text_from_text,
            }
            if content_type in content_handlers:
                return content_handlers[content_type](response)
            else:
                return "Unsupported content type"
        else:
            m = f"Failed to fetch the webpage. Status code: {response.status_code}"
            log(m)
            return m

# Main - Test
if __name__ == "__main__":
    print("Testing the document module")
    print("---------------------------")
    HOST = os.getenv("WEAVIATE_HOST", "localhost")
    # Test the document module
    print("Testing the document module")
    docs = Documents(host=HOST)
    print("Connecting to Weaviate")
    if not docs.connect():
        print("Unable to connect to Weaviate")
        exit(1)
    # Remove test collection
    print("Deleting test collection")
    docs.delete("test")
    print("Creating test collection")
    docs.create("test")
    # URL Test
    print("Adding a URL document")
    docs.add_file("test", "Twinkle, Twinkle, Little Star", "https://www.jasonacox.com/wordpress/archives/2141")
    # PDF Test
    print("Adding a PDF document")
    docs.add_file("test", "Wind the Clock", "test.pdf", "/tmp/tinyllm/test.pdf")
    # DOCX Test
    print("Adding a DOCX document")
    docs.add_file("test", "Wiring for Outcomes", "test.docx", "/tmp/tinyllm/test.docx")
    # TXT Test
    print("Adding a TXT document")
    docs.add_file("test", "Grid Bugs", "test.txt", "/tmp/tinyllm/test.txt")
    # List documents
    print("Listing documents")
    documents = docs.list_documents("test")
    print(f"   Number of files: {len(documents)}")
    for f in documents:
        print(f"{f}: {documents[f]}")
    # Get document
    print("Getting document with query: time")
    results = docs.get_documents("test", query="time", num_results=5)
    print(f"   Number: {len(results)}")
    uuid = []
    for d in results:
        print("   " + d["uuid"] + " - " + d["title"] + " - " + d["file"])   
        if d["doc_type"] != "PDF":
            uuid.append(d["uuid"])
    # Update document
    print("Updating document")
    docs.update_document("test", uuid[0], "Replace Title", "TXT", "updated.txt", "Updated content")
    # Delete document by ID
    print("Deleting document by ID")
    docs.delete_document("test", uuid[1])
    # Delete document by filename
    print("Deleting document by filename: test.docx")
    docs.delete_document("test", filename="test.pdf")
    # Get number of documents
    print("Getting number of documents")
    documents = docs.list_documents("test")
    print(f"   Number: {len(documents)}")
    # Delete collection
    print("Deleting test collection")
    docs.delete("test")
    # Close connection
    docs.close()
    log("Test complete")
