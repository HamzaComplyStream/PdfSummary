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
from scanned import is_scanned_pdf
from mongo_store import insert_document
from datetime import datetime
import prompts

today = datetime.today().strftime('%Y-%m-%d')

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
    file_name: str

###---------------------------------------Define Support Functions--------------------------------------------------------------###




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
        print(is_scanned_pdf(pdf_file))
        is_scanned = is_scanned_pdf(pdf_file)

        if is_scanned is True:
            return {"is_scanned":True,"text":None}
        else:
        
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
            return {"is_scanned":False,"text":extracted_text.strip()}
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Unexpected error extracting text from PDF: {str(e)}"
        )

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
        
    Raises:
        HTTPException: If file is too large, invalid type, or upload fails
    """
    try:
        # Check file size (10MB = 10 * 1024 * 1024 bytes)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
        file_size = len(file_bytes)
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"File size ({file_size / 1024 / 1024:.2f}MB) exceeds maximum allowed size of 10MB")

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

def bedrock_calling(system_prompt,prompt_type, pdf_text):
    """
    Call AWS Bedrock API with appropriate prompts
    
    Args:
        prompt_type (str): Type of prompt to use
        pdf_text (str): Extracted text from PDF
        
    Returns:
        JSONResponse: Structured analysis response
    """
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "messages": [
            
            {
                "role": "user",
                "content": f"""{system_prompt} \n\n {prompt_type}"""
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
    
    # Extract JSON from response
    start = response_text.find('{')
    end = response_text.rfind('}') + 1
    response_text = response_text[start:end]
    return json.loads(response_text)

def get_document_class(pdf_text: str) -> dict:
    """
    Classify document type using classification prompt
    
    Args:
        pdf_text (str): Extracted text from PDF
        
    Returns:
        dict: Document classification details
    """
    classification_prompt = prompts.user_prompt_classification(pdf_text)
    system_prompt = prompts.system_prompt_for_doc_classification
    return bedrock_calling(system_prompt =system_prompt,prompt_type = classification_prompt, pdf_text = pdf_text)

def get_document_analysis(doc_class: int, pdf_text: str) -> dict:
    """
    Generate appropriate document analysis based on classification
    
    Args:
        doc_class (int): Document class number
        pdf_text (str): Extracted text from PDF
        
    Returns:
        dict: Document analysis
    """
    prompt_mapping = {
        0: prompts.user_prompt_poi,
        1: prompts.user_prompt_poa,
        2: prompts.user_prompt_registration,
        3: prompts.user_prompt_ownership,
        4: prompts.user_prompt_tax_return,
        5: prompts.user_prompt_financial
    }

    system_prompt_mapping = {
        0: prompts.system_prompt_for_indentity_doc,
        1: prompts.system_prompt_for_poa_doc,
        2: prompts.system_prompt_for_registration_doc,
        3: prompts.system_prompt_for_ownership_doc,
        4: prompts.system_prompt_for_tax_return_doc,
        5: prompts.system_prompt_for_financial_doc
    }

    if doc_class not in prompt_mapping:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document class: {doc_class}"
        )

    user_prompt = prompt_mapping[doc_class](pdf_text, today)
    #print(user_prompt)
    system_prompt = system_prompt_mapping[doc_class]
    #print(system_prompt)

    #print(bedrock_calling(system_prompt = system_prompt,prompt_type =user_prompt,pdf_text = pdf_text))
    
    return bedrock_calling(system_prompt = system_prompt,prompt_type = user_prompt, pdf_text = pdf_text)

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
async def delete_s3_file(request: S3DeleteRequest):
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

@app.post("/generate_summary")
def generate_summary(request: S3DeleteRequest):
    try:
            bucket_name = request.bucket_name
            object_key = request.object_key
            file_name = request.file_name
            # Extract text from the given pdf path
            pdf_text = extract_text_from_s3_pdf(bucket_name = bucket_name, object_key = object_key)
            if pdf_text["is_scanned"] is True:
                return {"error" : "Current version does not parse scanned documents"}
            else:
                # First, classify the document
                classification_result = get_document_class(pdf_text)
                doc_class = classification_result.get('class')
                # Then generate appropriate analysis based on document class
                analysis_result = get_document_analysis(doc_class, pdf_text)                
                # Combine classification and analysis results
                final_response = {
                    "document_type": classification_result.get('category'),
                    "analysis": analysis_result
                }
                mongo_obj_id = insert_document(final_response)
                del final_response["_id"]
                final_response["mongo_obj_id"] = mongo_obj_id
                final_response = {"result":final_response}
                #response_text = json.dumps(final_response)
                return JSONResponse(content=final_response)        
     
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# For local development and testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
