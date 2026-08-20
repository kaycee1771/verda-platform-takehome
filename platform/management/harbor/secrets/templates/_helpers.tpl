{{- define "verdaHarborSecrets.assertAdmission" -}}
{{- if not .Values.gates.ciphertextsLocked -}}
{{- fail "Harbor SealedSecrets are blocked until ciphertextsLocked=true after namespace/name-scoped sealing" -}}
{{- end -}}
{{- range $name, $ciphertext := .Values.ciphertexts -}}
  {{- if not (regexMatch "^Ag[A-Za-z0-9+/=]{78,}$" $ciphertext) -}}
    {{- fail (printf "Harbor SealedSecret %s must be a real kubeseal ciphertext, not a sentinel" $name) -}}
  {{- end -}}
{{- end -}}
verified
{{- end -}}
