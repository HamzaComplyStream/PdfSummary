import PyPDF2
import pdfplumber
import pytesseract
from PIL import Image
import io

def is_scanned_pdf(pdf_path):
    """
    Determines if a PDF is scanned or pure text by analyzing its content.
    Returns True if scanned, False if pure text.
    """
    # Track results for each page
    pages_analysis = []
    
    try:
        # Open PDF with pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # Check for text content
                text = page.extract_text()
                
                # Check for images
                images = page.images
                
                # If page has no text but has images, likely scanned
                if (not text or text.isspace()) and len(images) > 0:
                    pages_analysis.append(True)
                # If page has text and no/few images, likely pure text
                elif text and not text.isspace():
                    pages_analysis.append(False)
                # If unclear, do additional checks
                else:
                    # Try to extract text using PyPDF2 as backup
                    with open(pdf_path, 'rb') as file:
                        reader = PyPDF2.PdfReader(file)
                        if len(reader.pages) > 0:
                            page_text = reader.pages[0].extract_text()
                            if page_text and not page_text.isspace():
                                pages_analysis.append(False)
                            else:
                                pages_analysis.append(True)
    
    except Exception as e:
        print(f"Error analyzing PDF: {e}")
        return None
    
    # If majority of pages appear scanned, consider the document scanned
    if pages_analysis:
        return sum(pages_analysis) / len(pages_analysis) >= 0.5
    return None

def analyze_pdf(pdf_path):
    """
    Provides detailed analysis of the PDF.
    """
    result = is_scanned_pdf(pdf_path)

    return {"scanned":result}
    
    # if result is True:
    #     print("This appears to be a scanned PDF document")
    # elif result is False:
    #     print("This appears to be a pure text PDF document")
    # else:
    #     print("Could not determine the PDF type")

# Usage example
if __name__ == "__main__":
    pdf_path = "example.pdf"
    scanned = analyze_pdf("./ComplyStreamDocs/HamzaPassport.pdf")
    print(scanned)
