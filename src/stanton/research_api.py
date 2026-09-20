"""Append-only research reviews and issued conclusions."""

from copy import deepcopy

from .common import digest, identifier, name, now, require
from .research_records import evidence_digest, issuance_data, review_data, review_template


class ResearchOperations:
    def research_template(self, target, *, run_id=None):
        run = self.store.run(run_id, target)
        state, _ = self.store.read(run["revision"])
        return review_template(run, state)

    def _research_record(self, registry, record_name, data, state, created_at):
        name(record_name)
        record = {**data, "name": record_name, "id": identifier("review" if registry == "research_reviews" else "issuance"),
                  "created_at": created_at}
        def mutate(current):
            require(digest(current) == digest(state), "Project changed during research operation; retry.", "stale_revision")
            records = current.setdefault(registry, {})
            require(record_name not in records, "Research records are immutable; choose a new name.")
            current["schema_version"] = 7
            records[record_name] = record
            warnings = deepcopy(record.get("findings", record.get("unresolved_findings", [])))
            if record.get("status") == "provisional":
                warnings.append({"code": "provisional-result", "message": "Issued as provisional; inspect remaining gaps and unresolved findings."})
            return {"record": deepcopy(record), "warnings": warnings}
        return self._edit("research-review" if registry == "research_reviews" else "report-issue", mutate)

    def research_review(self, review_name, document):
        state, revision = self.store.read()
        created_at = now()
        data = review_data(document, state, revision, self.store.run, lambda r: self.store.read(r)[0], created_at)
        return self._research_record("research_reviews", review_name, data, state, created_at)

    def report_issue(self, report_name, *, review, method=None, coverages=(.8, .9), definition=None, decisions=None):
        state, revision = self.store.read()
        data = issuance_data(state, revision, review, self.store.run, lambda r: self.store.read(r)[0],
                             method=method, coverages=coverages, definition=definition, decisions=decisions)
        return self._research_record("issued_reports", report_name, data, state, now())

    def research_show(self, record_name, *, issued=False):
        state, revision = self.store.read()
        registry = "issued_reports" if issued else "research_reviews"
        require(record_name in state.get(registry, {}), "Unknown research record.", "not_found")
        record = state[registry][record_name]
        current_basis = evidence_digest(state) == record["basis_sha256"]
        warnings = deepcopy(record.get("findings", record.get("unresolved_findings", [])))
        if not current_basis:
            warnings.append({"code": "stale-research-record", "message": "This historical record is unchanged, but current model or evidence differs; sample and review again for a current conclusion."})
        return {"record": record, "working_revision": revision, "current_basis": current_basis, "warnings": warnings}

    def research_status(self, target=None, *, run_id=None):
        state, revision = self.store.read()
        basis = evidence_digest(state)
        def selected(registry):
            return {key: {"run_id": r["run_id"], "target": r["target"],
                          "status": r["document"]["status"] if registry == "research_reviews" else r["status"],
                          "current_basis": r["basis_sha256"] == basis}
                    for key, r in state.get(registry, {}).items()
                    if (target is None or r["target"] == target) and (run_id is None or r["run_id"] == run_id)}
        return {"revision": revision, "reviews": selected("research_reviews"), "issued_reports": selected("issued_reports"),
                "verification": "Recorded agent judgments with mechanical binding checks; research quality is not certified."}
