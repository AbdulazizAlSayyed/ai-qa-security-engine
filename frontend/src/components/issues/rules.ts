/** Short labels for the backend's correlation rules (app/engines/correlation/keys.py). */
export const RULE_LABEL: Record<string, string> = {
  same_missing_header_and_origin: "Same missing header on the same origin",
  same_scanner_rule_and_origin: "Same scanner rule on the same origin",
  same_normalized_identity: "Same scanner and title on the same endpoint",
  same_qa_check_and_component: "Same QA check on the same component",
};
