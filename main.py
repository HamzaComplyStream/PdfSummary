import io
import os
import uuid
import boto3
import pdfplumber
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from botocore.exceptions import ClientError
from pydantic import BaseModel
import magic  # For file type validation
import json

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# AWS Configuration
session = boto3.Session(
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name='us-east-1'
)

###---------------------------------------Define Base models for each points of the apis---------------------------------------###
# Define Base model for requesting generate_summary endpoint
class RequestData(BaseModel):
    pdf_path: str

# Pydantic model for request body
class S3DeleteRequest(BaseModel):
    bucket_name: str
    object_key: str

###---------------------------------------Define Support Functions--------------------------------------------------------------###


# def extract_text_from_pdf(pdf_path: str) -> str:
#     """
#     Extract raw text from PDF
    
#     Args:
#         pdf_path (str): Path to PDF file
    
#     Returns:
#         str: Extracted text from PDF
#     """
#     try:
#         with pdfplumber.open(pdf_path) as pdf:
#             return "\n".join([page.extract_text() for page in pdf.pages])
#     except Exception as e:
#         raise HTTPException(status_code=400, detail=f"Error reading PDF: {str(e)}")
###-----------------------------------------------------------------------------------------------------------------------------###

###---------------------------------------Text Extraction Function --------------------------------------------------------------###

def extract_text_from_s3_pdf(bucket_name: str, object_key: str) -> str:
    """
    Extract raw text from PDF stored in S3 bucket
    
    Args:
        bucket_name (str): Name of the S3 bucket
        object_key (str): S3 object key of the PDF file
    
    Returns:
        str: Extracted text from PDF
    """
    try:
        # Create S3 client
        s3_client = boto3.client('s3')
        
        # Download PDF from S3
        print(bucket_name,object_key)
        try:
            s3_response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
            pdf_bytes = s3_response['Body'].read()
        except s3_client.exceptions.NoSuchKey:
            raise HTTPException(
                status_code=404, 
                detail=f"PDF not found in bucket {bucket_name} with key {object_key}"
            )
        except Exception as s3_error:
            raise HTTPException(
                status_code=500, 
                detail=f"Error accessing S3 object: {str(s3_error)}"
            )
        
        # Use BytesIO to create file-like object from S3 bytes
        pdf_file = io.BytesIO(pdf_bytes)
        
        # Extract text using pdfplumber
        try:
            with pdfplumber.open(pdf_file) as pdf:
                # Extract text from each page and join
                extracted_text = "\n".join([
                    page.extract_text() or "" for page in pdf.pages
                ])
        except Exception as pdf_error:
            raise HTTPException(
                status_code=400, 
                detail=f"Error parsing PDF: {str(pdf_error)}"
            )
        
        return extracted_text.strip()
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Unexpected error extracting text from PDF: {str(e)}"
        )
###-----------------------------------------------------------------------------------------------------------------------------###

###---------------------------------------Pdf upload to s3 Function --------------------------------------------------------------###

def upload_bytes_to_s3(
    file_bytes: bytes, 
    original_filename: str, 
    bucket_name: str = 'pdfsummarydocuments',
    prefix: str = 'uploads/'
) -> str:
    """
    Upload file bytes to S3 bucket
    
    Args:
        file_bytes (bytes): File content in bytes
        original_filename (str): Original filename
        bucket_name (str): S3 bucket name
        prefix (str): S3 prefix/folder
    
    Returns:
        str: S3 object key of uploaded file
    """
    try:
        # Validate file type (optional but recommended)
        file_type = magic.from_buffer(file_bytes, mime=True)
        if file_type not in ['application/pdf']:
            raise ValueError(f"Invalid file type. Expected PDF, got {file_type}")

        # Create S3 client
        s3_client = boto3.client('s3')

        # Generate unique filename
        file_extension = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        object_key = f"{prefix}{unique_filename}"

        # Upload file to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=file_bytes,
            ContentType='application/pdf'
        )

        return object_key

    except ClientError as e:
        print(f"S3 Upload Error: {e}")
        raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

def delete_file_from_s3(bucket_name: str, object_key: str) -> dict:
    """
    Delete a file from S3 bucket
    
    Args:
        bucket_name (str): Name of the S3 bucket
        object_key (str): Key of the object to delete
    
    Returns:
        dict: Deletion status and details
    """
    try:
        # Create S3 client
        s3_client = boto3.client('s3')
        
        # Verify object exists before deletion
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            # If object does not exist, raise specific exception
            if e.response['Error']['Code'] == "404":
                raise HTTPException(
                    status_code=404, 
                    detail=f"Object with key {object_key} not found in bucket {bucket_name}"
                )
            raise
        
        # Perform deletion
        response = s3_client.delete_object(
            Bucket=bucket_name,
            Key=object_key
        )
        
        # Return deletion details
        return {
            "status": "success",
            "message": f"Object {object_key} deleted successfully from bucket {bucket_name}",
            "response_metadata": response.get('ResponseMetadata', {})
        }
    
    except ClientError as e:
        # Handle specific S3 client errors
        error_code = e.response.get('Error', {}).get('Code')
        error_message = e.response.get('Error', {}).get('Message')
        
        # Map specific error codes to appropriate HTTP status
        error_map = {
            'AccessDenied': 403,
            'NoSuchBucket': 404,
            'NoSuchKey': 404
        }
        
        status_code = error_map.get(error_code, 500)
        
        raise HTTPException(
            status_code=status_code,
            detail=f"S3 Deletion Error: {error_message or 'Unknown error occurred'}"
        )
    
    except Exception as e:
        # Catch any unexpected errors
        raise HTTPException(
            status_code=500, 
            detail=f"Unexpected error during S3 deletion: {str(e)}"
        )

###---------------------------------------Define API End-points--------------------------------------------------------------###

@app.post("/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """
    API endpoint to upload PDF file
    
    Args:
        file (UploadFile): PDF file uploaded from frontend
    
    Returns:
        JSON response with S3 object key
    """
    try:
        # Read file bytes
        file_bytes = await file.read()
        
        # Upload to S3
        s3_object_key = upload_bytes_to_s3(
            file_bytes=file_bytes, 
            original_filename=file.filename
        )
        
        return JSONResponse(content={
            "message": "File uploaded successfully",
            "s3_object_key": s3_object_key,
            "original_filename": file.filename
        }, status_code=200)
    
    except HTTPException as e:
        return e

# API Endpoint for S3 File Deletion
@app.delete("/delete_file")
async def delete_file(request: S3DeleteRequest):
    """
    API endpoint to delete a file from S3 bucket
    
    Args:
        request (S3DeleteRequest): Request body with bucket name and object key
    
    Returns:
        dict: Deletion status and details
    """
    try:
        # Call deletion function
        result = delete_file_from_s3(
            bucket_name=request.bucket_name, 
            object_key=request.object_key
        )
        
        return result
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e

# API Endpoint for generating summary from given context of pdf
@app.post("/generate_summary")
def generate_summary(request: S3DeleteRequest):
    try:
        bucket_name = request.bucket_name
        object_key = request.object_key
        # pdf_path = request.pdf_path
        
        # Extract text from the given pdf path
        pdf_text = extract_text_from_s3_pdf(bucket_name = bucket_name, object_key = object_key)
        
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
