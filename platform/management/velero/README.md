# Velero

This tree retains the pinned Velero controller and namespaced backup policy. It is not a
restore-completeness claim. Credentials stay outside Git, restore permissions remain
separate from normal evaluator access, and destructive recovery requires explicit authorization.
Neither proves application consistency without a successful isolated restore test.
