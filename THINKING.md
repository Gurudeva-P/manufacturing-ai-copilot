# Product and Engineering Thinking

This file distinguishes my original writing from AI-assisted material. I have not presented AI suggestions as unaided reflection or as customer research. Sections labeled “suggested for my review” are drafts I should edit into my own view before submission.

## 1. Understand the user

### User profile — assignment-based, with assumptions labeled

**Role and setting from the assignment:** A shop-floor supervisor at Kaveri Precision Components Pvt. Ltd., Hosur Plant. The supplied documents cover TX-200 CNC maintenance, lockout/tagout safety, and incoming material inspection.

**Likely goals, inferred from the scenarios and documents:**
- Help an operator understand a TX-200 alarm and find the documented next step.
- Check the site’s lockout/tagout rules before maintenance work or restarting equipment.
- Help QC staff find the current incoming-inspection sampling and acceptance instructions.
- Verify where an answer came from before passing it on.

**Likely frustrations — product assumptions, not interview findings:**
- Searching long PDFs while an operator, technician, or inspector is waiting may take time.
- Multiple revisions can make it easy to find an obsolete instruction.
- A plain AI answer without a document, revision, and page reference is difficult to verify.
- A mobile user may be standing on the shop floor with limited time and a small screen.

**Context assumption:** The supervisor can use a phone connected to the plant Wi-Fi. This should be confirmed with a real customer; plant network policies may differ.

**What I would ask a supervisor:** [Write what you would ask about their current process, urgency, safety approvals, connectivity, and trust in cited instructions.]

## 2. User journey

### 2.1 My independent first user-journey draft

The following is my original draft, preserved verbatim:

> 1. First action: the supervisor opens the ai assisted copilot and asks his query for example(TX-200 machine is showing AL-104. What should I do?).  
> 2. After question: the application must first interpret the asked question using llm and pass the question to the RAG pipeline then the RAG pipeline would retrive the relevent data from the uploaded instruction using vector embedding and should return the answer  
> 3. What could go wrong: the potential issue would be ai cant retrive the irrelavant data or query which is not extracted from the given pdf

### 2.2 My revised first-draft wording

This is my follow-up wording, kept separate from the first version:

> 1. First action: the supervisor opens the ai assisted copilot and asks his query for example(TX-200 machine is showing AL-104. What should I do?)to the ai agent through the mobile.  
> 2. After question: the application should must first interpret the asked question using llm and pass the question to the RAG pipeline then the RAG pipeline would retreive the relevant data from the uploaded instruction using vector embedding and should return the answer  
> 3. What could go wrong: the potential issue would be ai cant retrieve the missing data or query which is not extracted from the given pdf and might encounter technical issue like chunking

### 2.3 Refined journey — AI-assisted version for my review

This version develops the user experience based on the critique. It is not represented as my original unaided draft.

1. A supervisor opens the copilot on a phone or tablet while connected to the plant network.
2. They ask, “The TX-200 is showing AL-104. What should I do?”
3. The app embeds the query and retrieves related chunks from the indexed plant documents.
4. The app passes the question and retrieved excerpts to Gemini.
5. The app shows a concise answer, plus document ID, revision, page, and evidence excerpt.
6. The supervisor verifies the source and follows the approved site procedure, escalating when the document requires it.
7. If the PDFs do not support an answer, the copilot says it cannot find enough information instead of inventing instructions.

Possible failures include PDF text extraction problems, a table split across chunks, unrelated retrieval, conflicting revisions, missing evidence, hallucination, network/API delay, an ambiguous question, or a phone that cannot reach the laptop. The app addresses some of these through page metadata, source citations, Rev 04 precedence, numeric-range retrieval, and abstention; it does not remove the need to follow site procedures.

## 3. AI challenge conversation

### Critique excerpts

The AI reviewer pointed out that my draft focused mostly on the technical query path. It said the journey should also explain what decision the supervisor needs to make, what answer they see, and what they should do if the system cannot find supporting evidence.

The reviewer also clarified that PDF ingestion occurs before a user asks a question, while query retrieval and answer generation occur at request time. It noted that an LLM does not have to rewrite every question before retrieval and that document citations help the supervisor verify a response.

### Skeptical product-manager questions

The following challenge questions are from the AI critique:

1. **Speed:** “A machine has stopped working. The supervisor is waiting for your application. What happens if the RAG pipeline takes 15 seconds to return an answer?”
2. **Trust:** “Your application returns: ‘Press RESET and continue.’ But it doesn't show where this instruction came from. Why should the supervisor trust the answer?”
3. **Safety:** “Can I remove another technician's lock if they have gone home? What if the LLM gives an incorrect answer?”
4. **Missing information:** “What is the salary of the factory supervisor? Your PDFs don't contain this information. How do you prevent the LLM from inventing an answer?”

Other issues the reviewer raised were extraction errors, chunking, retrieval failure, hallucination, ambiguous questions, outdated revisions, and network/API failures.

### Reflection on the challenge — suggested AI draft, review and personalize

This is a suggested starting point, not a claim about my personal opinions:

- **What I might agree with:** Source document, revision, and page citations matter because the supervisor needs to verify operational instructions. Unsupported questions should be answered with an explicit abstention.
- **What I might qualify or disagree with:** A fixed 15-second limit needs customer input. The acceptable wait may depend on the question, network conditions, and whether the issue is safety-critical. The app should communicate when it is still working rather than inventing a faster answer.
- **What I changed in the implementation:** I added source metadata and abstention, treated QC-SOP-014 Rev 04 as current, and fixed retrieval for a lot-size table after a 100-piece question exposed that a table row had been missed.

> Before submission, replace or edit these suggested statements so they accurately reflect what I agreed with, disagreed with, and changed.

## 4. Improvement implemented

### Revision-aware and table-aware retrieval

QC-SOP-014 is supplied in Rev 03 and Rev 04; Rev 04 supersedes Rev 03. The app stores document ID, revision, and page metadata and excludes superseded QC chunks from current answers. Its document list labels Rev 03 as superseded.

A regression question about a 100-piece lot exposed a second retrieval issue. Layout-aware PDF extraction now preserves table rows more effectively, and numeric-range matching recognizes that 100 falls inside the 91–500 band. The regression checks that the retrieved Rev 04 Page 1 content contains the 91–500 row and its 13-sample value; the answer itself is generated from the retrieved evidence, not hardcoded.

**Why this improvement was selected — suggested rationale:** The supplied revision pair illustrates why current instructions matter, and the sampling-plan regression demonstrates how a retrieval mistake could produce an incomplete answer. Showing revision and page makes it easier to verify the current procedure.

> In my own words, explain whether this was the right improvement to prioritize and what risk it reduces.

## 5. Final reflection

### Suggested reflection draft — AI-assisted; review before submission

The biggest implementation challenge was getting the correct QC sampling-plan row from the PDF. Initial retrieval ranked a Rev 04 procedure page above the page containing the lot-size table. I inspected the extracted text and chunks, changed extraction to layout mode, kept table rows together, added numeric range matching, and wrote a regression for a lot of 100. The test checks that the actual Rev 04 Page 1 source content supports 13 samples. This taught me that a similarity score alone is not enough for structured tables; revision control and page-level evidence matter too.

I would next compare the lightweight feature-hashing vectors with a pretrained embedding model using a labeled retrieval test set. I would also ask a supervisor to try the phone interface during a real shift. I am unsure how long a supervisor will wait for answers, what network access is available on the shop floor, which questions require immediate human escalation, and how local document updates are approved. I would ask the customer how procedures are versioned, who is authorized to act on safety answers, and how often the PDFs change. During deployment, I would verify that a phone on the plant Wi-Fi can reach the laptop and that citations remain readable.

**This is only a suggested draft. Edit it to reflect what I actually learned, what I would build next, what I am unsure about, what I would ask, and how I handled the challenge.**

### My own final reflection

- What I learned: [My response]
- What I would build next: [My response]
- What I am still unsure about: [My response]
- What I would ask the customer: [My response]
- Biggest challenge and how I handled it: [Review and personalize the suggested draft above]
