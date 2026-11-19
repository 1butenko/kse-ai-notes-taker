#!/bin/sh
# One-time setup: the IAM role GitHub Actions assumes (OIDC) to deploy the backend.
#   scripts/aws/github-deploy-role.sh        (needs admin AWS credentials: `aws login`)
# Creates or updates the GitHub OIDC provider and the role `kse-notes-github-deploy`.
# Only jobs in this repo's `production` environment can assume it, and it may only run
# AWS-RunShellScript on the backend instance and read the result. Prints the role ARN
# for the repository variable AWS_DEPLOY_ROLE_ARN (used by .github/workflows/deploy.yml).
set -eu

REPO="${REPO:-1butenko/kse-ai-notes-taker}"
REGION="${AWS_REGION:-eu-central-1}"
INSTANCE_ID="${INSTANCE_ID:-i-05052dea20cea067b}"
ROLE="${ROLE:-kse-notes-github-deploy}"
export MSYS_NO_PATHCONV=1 # Git Bash: keep ARNs and paths as they are

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
PROVIDER="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null
  echo "Created OIDC provider $PROVIDER"
fi

TRUST=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "$PROVIDER"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:$REPO:environment:production"
      }
    }
  }]
}
EOF
)

POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ec2:$REGION:$ACCOUNT:instance/$INSTANCE_ID",
        "arn:aws:ssm:$REGION::document/AWS-RunShellScript"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"],
      "Resource": "*"
    }
  ]
}
EOF
)

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" \
    --description "GitHub Actions deploy for $REPO" >/dev/null
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name deploy --policy-document "$POLICY"

echo "Role ARN: arn:aws:iam::$ACCOUNT:role/$ROLE"
echo "Set it with: gh variable set AWS_DEPLOY_ROLE_ARN --env production --body arn:aws:iam::$ACCOUNT:role/$ROLE"
