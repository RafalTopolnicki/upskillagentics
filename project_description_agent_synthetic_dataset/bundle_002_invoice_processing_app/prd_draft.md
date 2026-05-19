# Draft PRD: Invoice Processing Assistant

## MVP Features
- Upload invoice PDFs.
- Extract vendor name, invoice date, invoice number, due date, currency, subtotal, VAT, total, and line items.
- Export reviewed invoice data to CSV.
- Integrate directly with the accounting system through its API.
- Store all uploaded invoices and extracted data for 7 years.
- Use an external OCR provider if needed.

## Users
- Finance specialist
- Finance manager

## Acceptance Criteria
- User can upload a PDF invoice.
- User can review extracted fields.
- User can correct extraction errors.
- User can export invoice data.

## Suggested Stack
- Python backend
- React frontend
