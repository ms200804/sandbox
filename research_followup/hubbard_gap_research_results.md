# Research Results: Hubbard Lien Brief — Gap Filling
Date: 2026-03-31
Source: CourtListener via researcher.py (tiered Solr queries)

## GAP 1: Federal Court Authority to Modify a Charging Lien as Case Management

### Key Finding
The Fifth Circuit recognizes that federal courts have **inherent power to manage lawsuits** that includes supervising attorney fee disputes and charging liens — but draws a distinction between attorneys **discharged by the client** vs. attorneys who **voluntarily withdraw**.

### Critical Cases Found

**Broughten v. Voss, 634 F.2d 880 (5th Cir. 1981)** — MOST RELEVANT
- Directly addresses court's inherent authority over charging liens
- Holds: "It is true that there is a long tradition of sustaining jurisdiction to determine fees due an attorney dismissed by a client in a pending action."
- Recognizes the court's power to "condition the substitution of attorneys in litigation pending before it upon the client's either paying the attorney or posting security for the attorney's reasonable fees and disbursements"
- Key passage: "If, upon withdrawal, counsel is unable to secure payment for his services, the court may assume jurisdiction over a claim based on a charging lien over the proceeds of the lawsuit."
- **Important limitation:** Court distinguishes "between the case of a solicitor voluntarily withdrawing from a case and the case of a solicitor discharged by the client." BF withdrew, which is our more favorable posture.
- Note for Matt: This case is directly on point. The court vacated the district court's order but on jurisdictional grounds — the substance supports our argument that the court has inherent authority to supervise the lien.

**Villanueva v. CNA Ins. Cos., 868 F.2d 684 (5th Cir. 1989)** — Already cited in brief
- Confirms: federal courts may determine lien priority and order allocation of recovery among competing claimants
- "We also decide issues of law concerning SHRM's and CNA's right to assert an equitable lien on the proceeds of the settlement"

**Speaks v. Trikora Lloyd P.T., 838 F.2d 1436 (5th Cir. 1988)** — Already cited in brief
- Lien priority in maritime context, but the principle (federal court determines lien priorities) is generalizable

**Adams v. Westinghouse Electric Corp., 597 F.2d 570 (5th Cir. 1979)**
- Holds: "under Florida law an attorney is not permitted to withhold payment to a client of his money over and above the maximum amount of the attorney's claim against the client"
- Relevant for the proposition that a charging lien does not give the attorney unlimited control over client funds

**In re Diplomat Electric, Inc., 499 F.2d 342 (5th Cir. 1974)**
- Charging lien dispute in bankruptcy context
- Cited 29 times — well-established authority

**Persuasive (not binding but useful):**
- Rangel v. Save Mart, Inc., 140 N.M. 395 (N.M. Ct. App. 2006) — Court addressed sanctions based on filing of a charging lien; illustrates courts' supervisory role
- Santini v. Cleveland Clinic Florida, 65 So. 3d 22 (Fla. Dist. Ct. App. 2011) — Court enforcing/modifying charging lien
- Bistany v. PNC Bank, 585 F. Supp. 2d 179 (D. Mass. 2008) — Federal court addressing charging lien with inherent authority language

### Assessment for Brief
The brief already cites Villanueva and Speaks. **Broughten v. Voss should be added** — it's the most direct 5th Circuit authority on a federal court's inherent power to supervise a charging lien in pending litigation. The distinction it draws (discharged vs. withdrew) actually helps us since BF withdrew.

### Still need from Lexis
- Whether Broughten has been distinguished or limited on the lien-supervision point
- Any W.D. Tex. district court orders modifying or subordinating a charging lien (unpublished — CL coverage limited)

---

## GAP 2: Dispositive vs. Non-Dispositive Under § 636(b)(1)(A)

### Key Finding
The Fifth Circuit has extensive case law on the dispositive/non-dispositive line for magistrate referrals. The brief's footnote argues the motion is non-dispositive. The research supports this — **motions that don't resolve claims on the merits are generally non-dispositive** even if they have significant practical impact.

### Key Cases Found

**Merritt v. Int'l Brotherhood of Boilermakers, 649 F.2d 1013 (5th Cir. 1981)** — 140 cites
- Seminal 5th Circuit case on magistrate authority, including fee awards
- Affirmed magistrate's award of attorney's fees — treated as non-dispositive pretrial matter

**Parks v. Collins, 761 F.2d 1101 (5th Cir. 1985)** — 39 cites
- Challenged magistrate's order setting aside default judgment
- Addresses scope of magistrate's authority under § 636

**FDIC v. LeGrand, 43 F.3d 163 (5th Cir. 1995)** — 127 cites
- "The matter was referred to the federal magistrate"
- Major 5th Circuit case on scope of magistrate referral and consent

**Perales v. Casillas, 950 F.2d 1066 (5th Cir. 1992)** — 122 cites
- 5th Circuit authority on magistrate judge authority

**Castillo v. Frank, 70 F.3d 382 (5th Cir. 1995)** — 78 cites
- Also referenced in the sim's citation list; confirms magistrate referral standards

**In re 1994 Exxon Chemical Fire, 558 F.3d 378 (5th Cir. 2009)** — 144 cites
- Most-cited 5th Circuit case from the search; likely discusses magistrate authority in complex case management context

### Assessment for Brief
The footnote in the brief (fn. 1) already makes the non-dispositive argument. These cases provide ammunition if BF tries to challenge the magistrate's authority:
- Lien modification doesn't adjudicate BF's fee rights → non-dispositive
- Attorney fee-related matters have been treated as non-dispositive in the 5th Circuit (Merritt)
- Even if deemed dispositive, the alternative relief (subordination) preserves BF's interest

### Still need from Lexis
- Verify In re Exxon Chemical Fire's specific holding on dispositive vs. non-dispositive
- Any 5th Circuit case specifically addressing whether lien modification is dispositive
- Shepardize Merritt on the fee-award-as-non-dispositive point

---

## Researcher Tuning Notes

Things to potentially improve based on this run:
1. **Full-text extraction is truncated at 3k/5k chars** — some holdings appear later in the opinion. Consider scanning more text for key passages, or fetching full text for top-scored results only.
2. **Relevance scoring relies on snippets** which are often just the first paragraph. Consider also scoring based on `citeCount` more heavily — a 140-cite case is almost certainly more important than a 0-cite case.
3. **The phrase list needs ongoing expansion** — "non-dispositive", "pretrial matter", "magistrate judge" weren't in LEGAL_PHRASES so Gap 2 fell through to raw search. Adding common procedural terms would help.
