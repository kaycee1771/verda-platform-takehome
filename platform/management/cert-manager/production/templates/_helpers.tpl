{{- define "verdaCertProduction.assertStaging" -}}
{{- if not .Values.stagingIssuerVerified -}}
{{- fail "production issuance is blocked until stagingIssuerVerified=true is committed after live staging proof" -}}
{{- end -}}
{{- end -}}

{{- define "verdaCertProduction.hostname" -}}
{{- $hostname := required "hostname must be the accepted argocd.<IPv4-with-dashes>.nip.io name" .Values.hostname -}}
{{- if not (regexMatch "^argocd\\.[0-9]{1,3}(-[0-9]{1,3}){3}\\.nip\\.io$" $hostname) -}}
{{- fail "hostname must be the accepted argocd.<IPv4-with-dashes>.nip.io name" -}}
{{- end -}}
{{- $encoded := trimSuffix ".nip.io" (trimPrefix "argocd." $hostname) -}}
{{- range $octet := splitList "-" $encoded -}}
{{- if or (lt (atoi $octet) 0) (gt (atoi $octet) 255) -}}
{{- fail "hostname contains an invalid IPv4 octet" -}}
{{- end -}}
{{- end -}}
{{- $hostname -}}
{{- end -}}
