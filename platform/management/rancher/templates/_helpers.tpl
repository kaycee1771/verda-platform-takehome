{{- define "verdaRancher.hostname" -}}
{{- required "rancher.hostname is required" .Values.rancher.hostname -}}
{{- end -}}

{{- define "verdaRancher.assertAdmission" -}}
{{- if not .Values.gates.stagingCertificateVerified -}}
{{- fail "Rancher admission is blocked: set gates.stagingCertificateVerified=true only after the staging Certificate is Ready for this exact hostname" -}}
{{- end -}}
{{- if not .Values.gates.imageDigestsLocked -}}
{{- fail "Rancher admission is blocked: set gates.imageDigestsLocked=true only after all image digests are recorded in versions.lock.yaml" -}}
{{- end -}}
{{- $images := dict
      "rancher" .Values.rancher.image.tag
      "audit" .Values.rancher.auditLog.image.tag
      "shell" .Values.rancher.preUpgrade.image.tag -}}
{{- range $name, $reference := $images -}}
  {{- if not (regexMatch "^[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$" $reference) -}}
    {{- fail (printf "Rancher admission is blocked: %s image tag must contain an immutable sha256 digest" $name) -}}
  {{- end -}}
  {{- if regexMatch "@sha256:0{64}$" $reference -}}
    {{- fail (printf "Rancher admission is blocked: %s image digest cannot be the all-zero sentinel" $name) -}}
  {{- end -}}
{{- end -}}
{{- if ne .Values.rancher.preUpgrade.image.tag .Values.rancher.postDelete.image.tag -}}
{{- fail "Rancher admission is blocked: pre-upgrade and disabled post-delete hooks must use the same locked rancher/shell image" -}}
{{- end -}}
verified
{{- end -}}
