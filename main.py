# Import required libraries
import boto3
import json
import os
import pdfplumber
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# AWS Configuration
session = boto3.Session(
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name='us-east-1'
)

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract raw text from PDF
    
    Args:
        pdf_path (str): Path to PDF file
    
    Returns:
        str: Extracted text from PDF
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading PDF: {str(e)}")

# Define Base model for requesting generate_summary endpoint
class RequestData(BaseModel):
    pdf_path: str

# Create FastAPI APP
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.post("/generate_summary")
def generate_summary(request: RequestData):
    try:
        pdf_path = request.pdf_path
        
        # Extract text from the given pdf path
        pdf_text = extract_text_from_pdf(pdf_path)
        
        analysis_type = 'comprehensive'
        system_prompt = """You are an expert financial analyst with exceptional attention to detail. 
        Your task is to perform a comprehensive analysis of financial documents, 
        providing structured, actionable insights."""
        
        user_prompt = f"""Perform a {analysis_type} analysis of the following financial document:
        DOCUMENT TEXT:
        {pdf_text}
        
        COMPREHENSIVE ANALYSIS REQUIREMENTS:
        1. Identify key financial metrics and their significance
        2. Highlight potential risks or opportunities
        3. Compare metrics against industry benchmarks
        4. Provide a clear, concise summary with actionable insights
        
        Respond in the following structured JSON format:
        {{
            "summary": "High-level executive summary",
            "key_metrics": {{
                "metric_name": {{
                    "value": "specific value",
                    "interpretation": "expert analysis"
                }}
            }},
            "risks": ["Risk 1", "Risk 2"],
            "opportunities": ["Opportunity 1", "Opportunity 2"],
            "recommendation": "Strategic recommendation based on analysis"
        }}
        """
        
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "temperature": 0.3,
            "top_p": 0.9,
            "top_k": 250
        }
        
        bedrock = session.client('bedrock-runtime')
        body = json.dumps(payload)
        model_id = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
        
        response = bedrock.invoke_model(
            body=body,
            modelId=model_id,
            accept="application/json",
            contentType="application/json",
        )
        
        response_body = json.loads(response.get("body").read())
        response_text = response_body.get("content")[0].get("text")
        response_text = json.loads(response_text)
        
        return JSONResponse(content=response_text)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# For local development and testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)