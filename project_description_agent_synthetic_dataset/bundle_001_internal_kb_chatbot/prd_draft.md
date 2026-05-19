# Draft PRD: Internal Knowledge Base Chatbot

## Objective
Create a chatbot that answers employee questions using internal company documentation.

## MVP Scope
- Employees can ask natural-language questions.
- The system retrieves relevant internal documents.
- The chatbot returns an answer with source citations.
- Users can give thumbs-up / thumbs-down feedback.
- Admins can upload Markdown and PDF files.
- Slack integration is required in the MVP.
- Authentication must use company SSO.

## Non-Goals
- The chatbot will not modify source documents.
- The chatbot will not answer questions unrelated to company knowledge.

## Technical Preferences
- Backend: Python.
- Frontend: simple web app.
- Vector database: open to recommendation.
