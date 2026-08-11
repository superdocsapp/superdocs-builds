import asyncio
import os
import sys
import time
import uuid
import gc
from datetime import datetime
from sqlalchemy import select, text

# Set python path to current dir
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.database import AsyncSessionLocal, engine
from backend.app.models import Base, Document, DocumentChunk
from backend.app.services.ingestion import IngestionService
from backend.app.services.retrieval import RetrievalService

# Try to use psutil for real process memory, otherwise fallback to tracemalloc
try:
    import psutil
    def get_memory_usage_mb():
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
except ImportError:
    import tracemalloc
    tracemalloc.start()
    def get_memory_usage_mb():
        current, peak = tracemalloc.get_traced_memory()
        return peak / (1024 * 1024)

async def run_benchmark():
    print("==============================================================")
    print("            SUPERDOCS 40-DOCUMENT PERFORMANCE BENCHMARK        ")
    print("==============================================================")
    
    # 0. Setup database tables if not existing and clean them
    print("\n[0/5] Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE TABLE documents CASCADE;"))
        await session.commit()
    print("Database tables initialized and cleaned successfully.")

    # 1. Generate 40 unique synthetic documents (exceeding 2,500 characters each)
    print("\n[1/5] Generating 40 unique synthetic documents...")
    documents_data = []
    for i in range(1, 41):
        filename = f"diligence_doc_{i:02d}.txt"
        
        # Build multi-paragraph realistic corporate text
        paragraphs = [
            f"--- SECTION 1: EXECUTIVE BRIEFING FOR CORP-{i:02d} ---",
            "This document summarizes the key structural and financial details of the target acquisition candidate.",
            f"Operational audits conducted as of Q{i%4 + 1} indicate stable performance metrics.",
            f"--- SECTION 2: REVENUE AND GROWTH ANALYSIS ---",
            f"Historical revenue data for Corp-{i:02d} reflects consistent year-over-year gains.",
            f"Fact details for document {i:02d}: The revenue growth in Q{i%4 + 1} was {10 + i * 1.5}% and key contact is ContactPerson{i}.",
            "We expect this trajectory to remain stable due to long-term enterprise subscription contracts and recurring licensing agreements.",
            f"--- SECTION 3: LEGAL AND COMPLIANCE AUDIT ---",
            "All intellectual property filings have been verified with appropriate patent offices.",
            f"The legal counsel representing Corp-{i:02d} has confirmed no outstanding litigation or pending class-action lawsuits exist.",
            "There are no active material liabilities or unrecognized debt elements on the current balance sheet.",
            f"--- SECTION 4: CAP TABLE AND SHAREHOLDER DETAILS ---",
            "The capital structure is organized cleanly with common stock and preferred shares distributed among key founders.",
            f"Lead shareholder ContactPerson{i} maintains a direct controlling interest of {30 + (i * 0.5)}% of total equity.",
            "Remaining options are pool-reserved for employee incentive programs and future hires.",
            f"--- SECTION 5: INTERNAL TECHNOLOGY POLICY ---",
            "Software engineering guidelines require code reviews and automated testing integration.",
            "Production access is restricted using secure single sign-on authentication models and access monitoring systems.",
            "Backup cycles are performed on a daily basis with multi-region replication controls for disaster recovery scenarios."
        ]
        
        base_content = "\n\n".join(paragraphs)
        verbose_padding = f"\n\nAdditional historical diligence records for candidate {i:02d}:\n" + "\n".join(
            f"Line item record #{idx:03d}: Compliance verification checkpoint is fully satisfied for section {idx%5}. No critical flags raised."
            for idx in range(1, 25)
        )
        content_str = base_content + verbose_padding
        
        fact = f"The revenue growth in Q{i%4 + 1} was {10 + i * 1.5}% and key contact is ContactPerson{i}."
        documents_data.append((filename, content_str.encode("utf-8"), fact))
    print(f"Generated {len(documents_data)} unique text files (each > 2,500 characters).")

    # Get start memory
    mem_start = get_memory_usage_mb()
    t_ingest_start = time.time()
    
    # 2. Ingest all 40 documents through real IngestionService
    print("\n[2/5] Ingesting documents into database room...")
    async with AsyncSessionLocal() as session:
        ingest_service = IngestionService(session)
        latencies = []
        
        for filename, content, fact in documents_data:
            t_doc_start = time.time()
            # Call real IngestionService
            await ingest_service.ingest_document(filename, content)
            t_doc_end = time.time()
            latencies.append(t_doc_end - t_doc_start)
            
        await session.commit()
        
    t_ingest_end = time.time()
    total_ingest_time = t_ingest_end - t_ingest_start
    avg_ingest_latency = sum(latencies) / len(latencies)
    print(f"Ingested 40 documents in {total_ingest_time:.2f} seconds.")
    print(f"Average latency per document: {avg_ingest_latency * 1000:.1f} ms.")

    # 3. Verify they exist in DB and chunk count
    print("\n[3/5] Verifying database records...")
    async with AsyncSessionLocal() as session:
        res_docs = await session.execute(select(Document))
        db_docs = res_docs.scalars().all()
        
        res_chunks = await session.execute(select(DocumentChunk))
        db_chunks = res_chunks.scalars().all()
        
        print(f"Documents found in DB: {len(db_docs)} / 40")
        print(f"Total chunks created in DB: {len(db_chunks)}")
        
        if len(db_docs) < 40 or len(db_chunks) == 0:
            print("FAILED: Missing documents or chunks in database.")
            sys.exit(1)

    # 4. Execute target semantic queries to test isolation and accuracy
    print("\n[4/5] Running semantic retrieval accuracy tests...")
    queries = [
        # (query_text, expected_filename)
        ("revenue growth in Q2", "diligence_doc_01.txt"),
        ("key contact is ContactPerson10", "diligence_doc_10.txt"),
        ("revenue growth in Q1 was 40.0% and key contact is ContactPerson20", "diligence_doc_20.txt"),
        ("key contact is ContactPerson30", "diligence_doc_30.txt"),
        ("revenue growth in Q1 and key contact is ContactPerson40", "diligence_doc_40.txt"),
    ]
    
    t_retrieval_start = time.time()
    successful_retrievals = 0
    
    async with AsyncSessionLocal() as session:
        retrieval_service = RetrievalService(session)
        for query_text, expected_file in queries:
            print(f"Query: '{query_text}' -> Expected source: {expected_file}")
            results = await retrieval_service.search_diligence_chunks(query_text, limit=3)
            
            # Check if expected document is in top results
            filenames = [r["filename"] for r in results]
            print(f"  Retrieved filenames: {filenames}")
            if expected_file in filenames:
                successful_retrievals += 1
                print("  => MATCH (PASS)")
            else:
                print("  => MISMATCH (FAIL)")
                
    t_retrieval_end = time.time()
    total_retrieval_time = t_retrieval_end - t_retrieval_start
    retrieval_accuracy = (successful_retrievals / len(queries)) * 100
    avg_query_latency = (total_retrieval_time / len(queries)) * 1000
    
    # 5. Measure memory usage
    gc.collect()
    mem_peak = get_memory_usage_mb()
    mem_delta = mem_peak - mem_start
    
    print("\n[5/5] Performance Summary:")
    print("--------------------------------------------------------------")
    print(f"Documents: 40")
    print(f"Documents ingested: 40")
    print(f"Total chunks: {len(db_chunks)}")
    print(f"Ingestion time: {total_ingest_time:.2f} seconds")
    print(f"Retrieval queries run: {len(queries)}")
    print(f"Retrieval query average latency: {avg_query_latency:.1f} ms")
    print(f"Retrieval accuracy: {retrieval_accuracy:.1f}%")
    print(f"Peak memory: {mem_peak:.2f} MB")
    print(f"Memory growth during run: {mem_delta:.2f} MB")
    
    # Validation logic
    if len(db_docs) >= 40 and retrieval_accuracy >= 80.0:
        print("Result: PASS")
        print("--------------------------------------------------------------")
    else:
        print("Result: FAIL (Accuracy or document counts did not meet thresholds)")
        print("--------------------------------------------------------------")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
