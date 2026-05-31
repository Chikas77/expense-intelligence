# Categorize with Questions API Example

This example shows how to call the Flask endpoint `/categorize-with-questions` in a step-by-step way.

## Endpoint

`POST http://127.0.0.1:5000/categorize-with-questions`

## Request format

### First request

```json
{
  "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000.",
  "answer_path": []
}
```

### Follow-up request

```json
{
  "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000.",
  "question_level": "1",
  "user_answer": "A",
  "answer_path": ["A"]
}
```

### Continue the flow

```json
{
  "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000.",
  "question_level": "2A",
  "user_answer": "A1",
  "answer_path": ["A", "A1"]
}
```

### Example: unsure / clarification branch

```json
{
  "sms_message": "Sent Ksh 5,000 to JANE. New balance Ksh 12,000.",
  "question_level": "1",
  "user_answer": "C",
  "answer_path": ["C"]
}
```

That returns a clarification question such as `C1`:

```json
{
  "success": true,
  "needs_user_input": true,
  "question": {
    "question_level": "3",
    "level": 3,
    "question": "Is the money going OUT to someone/something, or is it staying in M-Pesa?",
    "options": [
      { "code": "C1", "label": "Going OUT to someone/something" },
      { "code": "C2", "label": "Staying in M-Pesa" }
    ]
  },
  "next_question_level": "3",
  "transaction": {
    "description": "Sent Ksh 5,000 to JANE.",
    "amount": 5000,
    "category": "transfer",
    "balance": 12000
  },
  "answer_path": ["C"]
}
```

## Expected response shapes

### When a question is returned

```json
{
  "success": true,
  "needs_user_input": true,
  "question": {
    "question_level": "1",
    "level": 1,
    "question": "Is this transaction money going TO a person or FOR a service/product?",
    "options": [
      { "code": "A", "label": "I sent/gave money to a person" },
      { "code": "B", "label": "I paid for a service or product" },
      { "code": "C", "label": "I'm unsure" }
    ]
  },
  "next_question_level": "1",
  "transaction": {
    "description": "Sent Ksh 5,000 to JANE.",
    "amount": 5000,
    "category": "transfer",
    "balance": 12000
  },
  "answer_path": []
}
```

### When a final category is returned

```json
{
  "success": true,
  "needs_user_input": false,
  "final_category": "Family Support",
  "sub_type": "Regular monthly support",
  "confidence": 1.0,
  "transaction": {
    "description": "Sent Ksh 5,000 to JANE.",
    "amount": 5000,
    "category": "transfer",
    "balance": 12000
  },
  "answer_path": ["A", "A1", "A1-i"]
}
```

## JavaScript client snippet

```js
const apiUrl = 'http://127.0.0.1:5000/categorize-with-questions';

async function postJson(body) {
  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.error || `HTTP ${response.status}`);
  }

  return response.json();
}

async function runCategorizationFlow(smsMessage) {
  let payload = { sms_message: smsMessage, answer_path: [] };
  let result = await postJson(payload);

  while (result.needs_user_input) {
    console.log('Question:', result.question.question);
    result.question.options.forEach(opt => {
      console.log(`${opt.code}: ${opt.label}`);
    });

    const answer = prompt('Enter option code:');
    if (!answer) {
      throw new Error('Answer required');
    }

    payload = {
      sms_message: smsMessage,
      question_level: result.next_question_level,
      user_answer: answer.trim(),
      answer_path: result.answer_path || [],
    };
    result = await postJson(payload);
  }

  console.log('Final category:', result.final_category);
  console.log('Sub-type:', result.sub_type);
  console.log('Answer path:', result.answer_path);
}

// Example usage
runCategorizationFlow('Sent Ksh 5,000 to JANE. New balance Ksh 12,000.')
  .catch(console.error);
```

## Notes

- Always send the same `sms_message` on each step.
- Send `answer_path` each time once the dialog begins, and the API will return the updated path.
- Use `next_question_level` from the previous response.
- `needs_user_input` tells you whether to continue.
- Question objects now include `question_level`.
- Final responses include `final_category`, `sub_type`, and `answer_path`.

## PDF upload and preview support

A new endpoint is available to preview extracted PDF text before categorization:

`POST http://127.0.0.1:5000/preview-pdf`

This endpoint accepts `multipart/form-data` with:
- `pdf_file`: the uploaded PDF file

It returns:
- `raw_text`: the text extracted from the PDF
- `candidates`: the M-Pesa-style candidate lines found in the text
- `message`: guidance on whether the preview contains likely transaction lines

After previewing the extracted lines, select the correct candidate and send that line text to `/categorize-with-questions`.

For scanned or image-based PDFs, text extraction falls back to OCR using Tesseract.

### Tesseract installation

You need two pieces:
1. Python packages:
   - `pdfplumber`
   - `Pillow`
   - `pytesseract`

2. The Tesseract binary installed on your system.

On Windows:
- Download the Tesseract installer from https://github.com/tesseract-ocr/tesseract/releases
- Install it, then add the installation folder (for example `C:\Program Files\Tesseract-OCR`) to your `PATH`

On Linux:
- `sudo apt install tesseract-ocr` (Debian/Ubuntu)

On macOS:
- `brew install tesseract`

If Tesseract is not installed, PDF preview will still attempt direct text extraction from the PDF, but OCR for scanned pages will not run.

### PDF structure notes

A monthly M-Pesa statement or export often contains many lines. The preview endpoint extracts all page text and highlights the candidate lines that look like M-Pesa transactions.

If the wrong PDF is uploaded, you can reject the preview and upload the correct document instead. This helps avoid running the categorization flow on non-M-Pesa files.
