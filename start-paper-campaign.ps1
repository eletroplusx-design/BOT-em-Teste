[CmdletBinding(DefaultParameterSetName = 'Review')]
param(
    [Parameter(Mandatory = $false, ParameterSetName = 'Review')]
    [switch]$Review,

    [Parameter(Mandatory = $false, ParameterSetName = 'Prepare')]
    [switch]$Prepare,

    [Parameter(Mandatory = $false, ParameterSetName = 'StartSession')]
    [switch]$StartSession,

    [string]$ProjectRoot = (Get-Location).Path,
    [string]$PaperDataDir = 'C:\Users\Vitor\BotTraderPaperData',
    [string]$PythonExe = (Join-Path $ProjectRoot 'venv\Scripts\python.exe'),
    [string]$ReferenceConfigFile = (Join-Path $ProjectRoot 'reference-config.json'),
    [string]$PromotionPolicyFile = (Join-Path $ProjectRoot 'promotion_policy.json'),
    [string]$CampaignPolicyFile = (Join-Path $ProjectRoot 'campaign_policy.json'),
    [string]$OperationalPlanPath = (Join-Path $PaperDataDir 'operational-plan.json'),
    [string]$CampaignId = 'paper-operational-campaign',
    [string]$StrategyVersion = 'v4_walk_forward',
    [string]$Symbol = 'BTCUSDT',
    [string]$Interval = '1h',
    [string]$Provider = 'trusted_market_data_service',
    [int]$Limit = 1000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ConvertFromJsonSupportsDepth = $null

function Fail {
    param([Parameter(Mandatory = $true)][string]$Message)
    throw $Message
}

function Convert-ToUtcIso {
    param([Parameter(Mandatory = $true)][datetime]$Value)
    return $Value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

function Convert-FromUtcIso {
    param([Parameter(Mandatory = $true)][string]$Value)
    $dto = [datetimeoffset]::Parse($Value, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
    return $dto.UtcDateTime
}

function ConvertFrom-JsonCompatible {
    param([Parameter(Mandatory = $true)][string]$JsonText)
    if ([string]::IsNullOrWhiteSpace($JsonText)) {
        Fail 'JSON is invalid.'
    }
    if ($null -eq $script:ConvertFromJsonSupportsDepth) {
        $script:ConvertFromJsonSupportsDepth = (Get-Command ConvertFrom-Json).Parameters.ContainsKey('Depth')
    }
    try {
        $arguments = @{}
        if ($script:ConvertFromJsonSupportsDepth) {
            $arguments['Depth'] = 100
        }
        return ($JsonText | ConvertFrom-Json @arguments -ErrorAction Stop)
    } catch {
        Fail 'JSON is invalid.'
    }
}

function Assert-StrictBool {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $false)][bool]$Expected
    )
    if ($Value -isnot [bool]) {
        Fail "$Name must be a boolean."
    }
    if ($PSBoundParameters.ContainsKey('Expected') -and $Value -ne $Expected) {
        $expectedText = if ($Expected) { 'true' } else { 'false' }
        Fail "$Name must be $expectedText."
    }
}

function Assert-StringValue {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value)) {
        Fail "$Name must be a non-empty string."
    }
}

function Assert-ObjectHasKeys {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string[]]$Keys,
        [Parameter(Mandatory = $true)][string]$Name
    )
    foreach ($key in $Keys) {
        if (-not ($Object.PSObject.Properties.Name -contains $key)) {
            Fail "$Name is missing $key."
        }
    }
}

function Read-JsonFileStrict {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail "$Label not found."
    }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Fail "$Label is empty."
    }
    try {
        return ConvertFrom-JsonCompatible -JsonText $raw
    } catch {
        Fail "$Label is invalid JSON."
    }
}

function Write-Utf8NoBomTextAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $destination = [System.IO.Path]::GetFullPath($Path)
    $directory = [System.IO.Path]::GetDirectoryName($destination)
    if ([string]::IsNullOrWhiteSpace($directory)) {
        $directory = (Get-Location).Path
    }
    if (-not (Test-Path -LiteralPath $directory)) {
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    $temp = [System.IO.Path]::Combine($directory, [System.IO.Path]::GetRandomFileName() + '.tmp')
    $encoding = [System.Text.UTF8Encoding]::new($false)
    try {
        [System.IO.File]::WriteAllText($temp, $Content, $encoding)
        if ([System.IO.File]::Exists($destination)) {
            $backup = [System.IO.Path]::Combine($directory, [System.IO.Path]::GetRandomFileName() + '.bak')
            try {
                [System.IO.File]::Replace($temp, $destination, $backup, $true)
            } finally {
                if ([System.IO.File]::Exists($backup)) {
                    [System.IO.File]::Delete($backup)
                }
            }
        } else {
            [System.IO.File]::Move($temp, $destination)
        }
    } catch {
        if ([System.IO.File]::Exists($temp)) {
            [System.IO.File]::Delete($temp)
        }
        throw
    }
}

function Invoke-PaperOperations {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Fail "python executable not found."
    }
    $stdout = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName() + '.out.log')
    $stderr = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName() + '.err.log')
    $allArguments = @('-m', 'paper_operations') + $Arguments
    try {
        $process = Start-Process -FilePath $PythonExe -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList $allArguments
        $outText = if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout -Raw -Encoding UTF8 } else { '' }
        $errText = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -Encoding UTF8 } else { '' }
        if ($process.ExitCode -ne 0) {
            if (-not [string]::IsNullOrWhiteSpace($errText)) {
                Write-Host $errText.Trim()
            }
            Fail "paper_operations command failed."
        }
        if ([string]::IsNullOrWhiteSpace($outText)) {
            return $null
        }
        return ConvertFrom-JsonCompatible -JsonText $outText
    } finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue
    }
}

function Get-CurrentWindow {
    $localStart = (Get-Date).Date.AddDays(1).AddHours(9)
    $utcStart = $localStart.ToUniversalTime()
    $utcEnd = $utcStart.AddDays(90)
    return [pscustomobject]@{
        start_local = $localStart
        start_utc = $utcStart
        end_utc = $utcEnd
    }
}

function New-ReferenceConfig {
    return [pscustomobject]@{
        symbol = $Symbol
        interval = $Interval
        limit = $Limit
        strategy_version = $StrategyVersion
        provider = $Provider
    }
}

function Assert-OperationalReference {
    param(
        [Parameter(Mandatory = $true)]$Reference,
        [Parameter(Mandatory = $true)][string]$ReferencePath
    )
    Assert-ObjectHasKeys -Object $Reference -Keys @('operational_provenance', 'walk_forward') -Name 'reference'
    Assert-ObjectHasKeys -Object $Reference.operational_provenance -Keys @('synthetic_test_data', 'reference_hash', 'scope_hash') -Name 'reference.operational_provenance'
    Assert-ObjectHasKeys -Object $Reference.walk_forward -Keys @('manifest', 'summary', 'windows') -Name 'reference.walk_forward'
    Assert-ObjectHasKeys -Object $Reference.walk_forward.manifest -Keys @('runner_trusted', 'execution_contract') -Name 'reference.walk_forward.manifest'
    Assert-ObjectHasKeys -Object $Reference.walk_forward.manifest.execution_contract -Keys @('paper_only', 'symbol', 'interval', 'strategy_version') -Name 'reference.walk_forward.manifest.execution_contract'
    Assert-StrictBool -Value $Reference.operational_provenance.synthetic_test_data -Name 'synthetic_test_data' -Expected:$false
    Assert-StrictBool -Value $Reference.walk_forward.manifest.runner_trusted -Name 'runner_trusted' -Expected:$true
    Assert-StrictBool -Value $Reference.walk_forward.manifest.execution_contract.paper_only -Name 'paper_only' -Expected:$true
    if ($Reference.walk_forward.manifest.execution_contract.symbol -ne $Symbol) {
        Fail 'reference symbol does not match the requested campaign symbol.'
    }
    if ($Reference.walk_forward.manifest.execution_contract.interval -ne $Interval) {
        Fail 'reference interval does not match the requested campaign interval.'
    }
    if ($Reference.walk_forward.manifest.execution_contract.strategy_version -ne $StrategyVersion) {
        Fail 'reference strategy_version does not match the requested campaign strategy version.'
    }
    return $Reference
}

function Assert-PlanSchema {
    param([Parameter(Mandatory = $true)]$Plan)
    Assert-ObjectHasKeys -Object $Plan -Keys @(
        'schema_version',
        'status',
        'paper_data_dir',
        'campaign_id',
        'campaign_hash',
        'cohort_hash',
        'binding_hash',
        'reference_hash',
        'decision_hash',
        'reference_output_path',
        'promotion_decision_path',
        'window_start_utc',
        'window_end_utc',
        'backup_dir',
        'restore_verify_dir',
        'session_id',
        'session_state',
        'runtime_contract_hash'
    ) -Name 'operational-plan'
    Assert-StrictBool -Value $Plan.paper_only -Name 'paper_only' -Expected:$true
}

function Assert-PlanConsistency {
    param(
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)]$Reference,
        [Parameter(Mandatory = $true)]$Decision,
        [Parameter(Mandatory = $false)]$Cohort,
        [Parameter(Mandatory = $false)]$Campaign,
        [Parameter(Mandatory = $false)]$BackupVerify,
        [Parameter(Mandatory = $false)]$RestoreVerify,
        [Parameter(Mandatory = $false)]$BindingHash
    )
    Assert-PlanSchema -Plan $Plan
    if ((Resolve-Path -LiteralPath $Plan.paper_data_dir).Path -ne (Resolve-Path -LiteralPath $PaperDataDir).Path) {
        Fail 'paper_data_dir mismatch.'
    }
    if ($Plan.campaign_id -ne $CampaignId) { Fail 'campaign_id mismatch.' }
    Assert-StringValue -Value $Plan.cohort_hash -Name 'cohort_hash'
    Assert-StringValue -Value $Plan.campaign_hash -Name 'campaign_hash'
    Assert-StringValue -Value $Plan.binding_hash -Name 'binding_hash'
    if ($Plan.reference_hash -ne $Reference.operational_provenance.reference_hash) { Fail 'reference_hash mismatch.' }
    if ($Plan.decision_hash -ne $Decision.decision_hash) { Fail 'decision_hash mismatch.' }
    if ($Plan.reference_output_path -ne (Resolve-Path -LiteralPath $Reference._source_path).Path) { Fail 'reference_output_path mismatch.' }
    if ($Plan.promotion_decision_path -ne (Resolve-Path -LiteralPath $Decision._source_path).Path) { Fail 'promotion_decision_path mismatch.' }
    Assert-StrictBool -Value $Reference.operational_provenance.synthetic_test_data -Name 'synthetic_test_data' -Expected:$false
    Assert-StrictBool -Value $Reference.walk_forward.manifest.runner_trusted -Name 'runner_trusted' -Expected:$true
    Assert-StrictBool -Value $Reference.walk_forward.manifest.execution_contract.paper_only -Name 'paper_only' -Expected:$true
    if ($PSBoundParameters.ContainsKey('BackupVerify')) {
        Assert-ObjectHasKeys -Object $BackupVerify -Keys @('backup_dir', 'verified') -Name 'backup verification'
        Assert-StrictBool -Value $BackupVerify.verified -Name 'backup.verified' -Expected:$true
        $expectedBackupDir = (Resolve-Path -LiteralPath $Plan.backup_dir).Path
        $actualBackupDir = (Resolve-Path -LiteralPath (Join-Path (Join-Path $PaperDataDir 'backups') $BackupVerify.backup_dir)).Path
        if ($expectedBackupDir -ne $actualBackupDir) {
            Fail 'backup_dir mismatch.'
        }
    }
    if ($PSBoundParameters.ContainsKey('RestoreVerify')) {
        Assert-ObjectHasKeys -Object $RestoreVerify -Keys @('backup_dir', 'verified') -Name 'restore verification'
        Assert-StrictBool -Value $RestoreVerify.verified -Name 'restore.verified' -Expected:$true
        $expectedRestoreVerifyDir = (Resolve-Path -LiteralPath $Plan.restore_verify_dir).Path
        $actualRestoreVerifyDir = (Resolve-Path -LiteralPath (Join-Path (Join-Path $PaperDataDir 'backups') $RestoreVerify.backup_dir)).Path
        if ($expectedRestoreVerifyDir -ne $actualRestoreVerifyDir) {
            Fail 'restore_verify_dir mismatch.'
        }
    }
    if ($PSBoundParameters.ContainsKey('Cohort')) {
        Assert-ObjectHasKeys -Object $Cohort -Keys @('cohort_hash', 'strategy_version', 'symbol', 'interval', 'inclusion_rule', 'period_start_utc', 'period_end_utc') -Name 'cohort'
        if ($Cohort.cohort_hash -ne $Plan.cohort_hash) { Fail 'cohort_hash mismatch.' }
        if ($Cohort.strategy_version -ne $StrategyVersion) { Fail 'cohort strategy_version mismatch.' }
        if ($Cohort.symbol -ne $Symbol) { Fail 'cohort symbol mismatch.' }
        if ($Cohort.interval -ne $Interval) { Fail 'cohort interval mismatch.' }
        if ($Cohort.inclusion_rule -ne 'sqlite_all_sessions') { Fail 'cohort inclusion_rule mismatch.' }
        if ($Cohort.period_start_utc -ne $Plan.window_start_utc) { Fail 'cohort period_start_utc mismatch.' }
        if ($Cohort.period_end_utc -ne $Plan.window_end_utc) { Fail 'cohort period_end_utc mismatch.' }
    }
    if ($PSBoundParameters.ContainsKey('Campaign')) {
        Assert-ObjectHasKeys -Object $Campaign -Keys @('campaign_hash', 'campaign_id', 'campaign_state', 'cohort_hash', 'strategy_version', 'symbol', 'interval', 'inclusion_rule', 'period_start_utc', 'period_end_utc') -Name 'campaign'
        if ($Campaign.campaign_hash -ne $Plan.campaign_hash) { Fail 'campaign_hash mismatch.' }
        if ($Campaign.campaign_id -ne $Plan.campaign_id) { Fail 'campaign_id mismatch.' }
        if ($Campaign.campaign_state -notin @('PREPARED', 'RUNNING')) { Fail 'campaign state mismatch.' }
        if ($Campaign.cohort_hash -ne $Plan.cohort_hash) { Fail 'campaign cohort_hash mismatch.' }
        if ($Campaign.strategy_version -ne $StrategyVersion) { Fail 'campaign strategy_version mismatch.' }
        if ($Campaign.symbol -ne $Symbol) { Fail 'campaign symbol mismatch.' }
        if ($Campaign.interval -ne $Interval) { Fail 'campaign interval mismatch.' }
        if ($Campaign.inclusion_rule -ne 'sqlite_all_sessions') { Fail 'campaign inclusion_rule mismatch.' }
        if ($Campaign.period_start_utc -ne $Plan.window_start_utc) { Fail 'campaign period_start_utc mismatch.' }
        if ($Campaign.period_end_utc -ne $Plan.window_end_utc) { Fail 'campaign period_end_utc mismatch.' }
    }
    if ($PSBoundParameters.ContainsKey('BindingHash')) {
        Assert-StringValue -Value $BindingHash -Name 'binding_hash'
        if ($Plan.binding_hash -ne $BindingHash) {
            Fail 'binding_hash mismatch.'
        }
    }
}

function Get-ActiveRuntimeSession {
    param([Parameter(Mandatory = $true)][string]$DataDir)
    $result = Invoke-PaperOperations @('--data-dir', $DataDir, 'session', 'active')
    if ($null -eq $result) {
        Fail 'session active returned no payload.'
    }
    if ($result.status -eq 'NONE') {
        return $null
    }
    if ($result.status -ne 'FOUND') {
        Fail 'session active returned an unexpected status.'
    }
    Assert-StringValue -Value $result.session_id -Name 'session_id'
    Assert-StringValue -Value $result.contract_hash -Name 'contract_hash'
    Assert-StringValue -Value $result.decision_hash -Name 'decision_hash'
    Assert-StringValue -Value $result.session_started_utc -Name 'session_started_utc'
    return $result
}

function Get-PlanPath {
    return $OperationalPlanPath
}

function Load-OperationalPlan {
    param([Parameter(Mandatory = $true)][string]$Path)
    $plan = Read-JsonFileStrict -Path $Path -Label 'operational plan'
    Assert-PlanSchema -Plan $plan
    return $plan
}

function Save-OperationalPlan {
    param([Parameter(Mandatory = $true)]$Plan, [Parameter(Mandatory = $true)][string]$Path)
    $json = ($Plan | ConvertTo-Json -Depth 50 -Compress)
    Write-Utf8NoBomTextAtomic -Path $Path -Content $json
}

function Invoke-Prepare {
    $window = Get-CurrentWindow
    $windowStartUtc = Convert-ToUtcIso $window.start_utc
    $windowEndUtc = Convert-ToUtcIso $window.end_utc

    if (-not (Test-Path -LiteralPath $PaperDataDir)) {
        [System.IO.Directory]::CreateDirectory($PaperDataDir) | Out-Null
    }

    $env:PAPER_DATA_DIR = $PaperDataDir

    Invoke-PaperOperations @('--data-dir', $PaperDataDir, 'initialize') | Out-Null

    $referenceConfig = New-ReferenceConfig
    if (-not (Test-Path -LiteralPath $ReferenceConfigFile)) {
        Fail 'reference config file not found.'
    }
    $referenceResult = Invoke-PaperOperations @('phase5-reference', '--input', $ReferenceConfigFile)
    $referenceOutputPath = if ($referenceResult.output) { [string]$referenceResult.output } else { (Join-Path $PaperDataDir 'reference.json') }
    $reference = Read-JsonFileStrict -Path $referenceOutputPath -Label 'reference output'
    $reference._source_path = $referenceOutputPath
    Assert-OperationalReference -Reference $reference -ReferencePath $referenceOutputPath | Out-Null

    if (-not (Test-Path -LiteralPath $PromotionPolicyFile)) { Fail 'promotion policy file not found.' }
    $decisionResult = Invoke-PaperOperations @('promotion-decision', '--reference-file', $referenceOutputPath, '--policy-file', $PromotionPolicyFile)
    $decisionOutputPath = if ($decisionResult.output) { [string]$decisionResult.output } else { (Join-Path $PaperDataDir 'promotion_decision.json') }
    $decision = Read-JsonFileStrict -Path $decisionOutputPath -Label 'promotion decision output'
    $decision._source_path = $decisionOutputPath
    Assert-StringValue -Value $decision.decision_hash -Name 'decision_hash'
    Assert-StrictBool -Value $decision.paper_limits.paper_only -Name 'decision.paper_only' -Expected:$true
    if ($decision.status -ne 'APPROVED_FOR_MONITORED_PAPER') {
        Fail 'promotion decision is not approved for monitored paper.'
    }

    if (-not (Test-Path -LiteralPath $CampaignPolicyFile)) { Fail 'campaign policy file not found.' }
    $cohort = Invoke-PaperOperations @(
        'cohort', 'prepare',
        '--strategy-version', $StrategyVersion,
        '--symbol', $Symbol,
        '--interval', $Interval,
        '--inclusion-rule', 'sqlite_all_sessions',
        '--period-start-utc', $windowStartUtc,
        '--period-end-utc', $windowEndUtc,
        '--runtime-db', (Join-Path $PaperDataDir 'paper_runtime.db')
    )
    $campaign = Invoke-PaperOperations @(
        'campaign', 'prepare',
        '--campaign-id', $CampaignId,
        '--policy-file', $CampaignPolicyFile,
        '--reference-file', $referenceOutputPath,
        '--strategy-version', $StrategyVersion,
        '--symbol', $Symbol,
        '--interval', $Interval,
        '--inclusion-rule', 'sqlite_all_sessions',
        '--period-start-utc', $windowStartUtc,
        '--period-end-utc', $windowEndUtc,
        '--cohort-hash', $cohort.cohort_hash,
        '--runtime-db', (Join-Path $PaperDataDir 'paper_runtime.db'),
        '--campaign-db', (Join-Path $PaperDataDir 'paper_evaluation_campaign.db')
    )
    $binding = Invoke-PaperOperations @(
        'campaign', 'bind',
        '--campaign-id', $CampaignId,
        '--decision-file', $decisionOutputPath,
        '--campaign-db', (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'),
        '--data-dir', $PaperDataDir
    )

    $backup = Invoke-PaperOperations @(
        'backup', 'create',
        '--data-dir', $PaperDataDir,
        '--backup-name', ("{0:yyyyMMddHHmmss}-campaign" -f (Get-Date).ToUniversalTime())
    )
    $restoreVerify = Invoke-PaperOperations @('restore', 'verify', '--backup-dir', $backup.backup_dir)
    $doctorReport = Invoke-PaperOperations @('doctor', '--data-dir', $PaperDataDir)
    if ($doctorReport.status -ne 'READY') {
        Fail 'doctor is not ready.'
    }

    $plan = [pscustomobject]@{
        schema_version = 1
        status = 'PREPARED'
        paper_data_dir = (Resolve-Path -LiteralPath $PaperDataDir).Path
        campaign_id = $CampaignId
        strategy_version = $StrategyVersion
        symbol = $Symbol
        interval = $Interval
        provider = $Provider
        limit = $Limit
        reference_output_path = (Resolve-Path -LiteralPath $referenceOutputPath).Path
        promotion_decision_path = (Resolve-Path -LiteralPath $decisionOutputPath).Path
        backup_dir = (Resolve-Path -LiteralPath $backup.backup_dir).Path
        restore_verify_dir = (Resolve-Path -LiteralPath $restoreVerify.backup_dir).Path
        window_start_utc = $windowStartUtc
        window_end_utc = $windowEndUtc
        cohort_hash = $cohort.cohort_hash
        campaign_hash = $campaign.campaign_hash
        binding_hash = $binding.binding_hash
        reference_hash = $reference.operational_provenance.reference_hash
        decision_hash = $decision.decision_hash
        paper_only = $true
        session_id = $null
        session_state = $null
        runtime_contract_hash = $null
    }
    Save-OperationalPlan -Plan $plan -Path (Get-PlanPath)

    Write-Host 'Prepared operational plan created successfully.'
    Write-Host ('  reference: {0}' -f $plan.reference_output_path)
    Write-Host ('  promotion decision: {0}' -f $plan.promotion_decision_path)
    Write-Host ('  backup: {0}' -f $plan.backup_dir)
    Write-Host ('  restore verify: {0}' -f $plan.restore_verify_dir)
}

function Invoke-SessionStart {
    $planPath = Get-PlanPath
    $plan = Load-OperationalPlan -Path $planPath
    $reference = Read-JsonFileStrict -Path $plan.reference_output_path -Label 'reference output'
    $reference._source_path = $plan.reference_output_path
    Assert-OperationalReference -Reference $reference -ReferencePath $plan.reference_output_path | Out-Null
    $decision = Read-JsonFileStrict -Path $plan.promotion_decision_path -Label 'promotion decision output'
    $decision._source_path = $plan.promotion_decision_path
    Assert-StringValue -Value $decision.decision_hash -Name 'decision_hash'
    Assert-StrictBool -Value $decision.paper_limits.paper_only -Name 'decision.paper_only' -Expected:$true
    if ($decision.status -ne 'APPROVED_FOR_MONITORED_PAPER') {
        Fail 'promotion decision is not approved for monitored paper.'
    }
    Assert-PlanConsistency -Plan $plan -Reference $reference -Decision $decision

    $cohort = Invoke-PaperOperations @('cohort', 'status', '--runtime-db', (Join-Path $PaperDataDir 'paper_runtime.db'), '--cohort-hash', $plan.cohort_hash)
    $campaign = Invoke-PaperOperations @('campaign', 'status', '--campaign-id', $plan.campaign_id, '--campaign-db', (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'))
    Assert-PlanConsistency -Plan $plan -Reference $reference -Decision $decision -Cohort $cohort -Campaign $campaign

    if ($plan.status -eq 'SESSION_STARTED') {
        if (-not $plan.session_id) {
            Fail 'session_started state requires a persisted session_id.'
        }
        $runtimeStatus = Invoke-PaperOperations @('session', 'status', '--session-id', $plan.session_id, '--data-dir', $PaperDataDir)
        if ($runtimeStatus.session_id -ne $plan.session_id) {
            Fail 'persisted runtime session id mismatch.'
        }
        switch ($runtimeStatus.state) {
            'RUNNING' {
            }
            'COMPLETED' {
                Fail 'persisted runtime session is completed.'
            }
            'SUSPENDED' {
                Fail 'persisted runtime session is suspended.'
            }
            'FAILED' {
                Fail 'persisted runtime session failed.'
            }
            default {
                Fail 'persisted runtime session returned an unknown state.'
            }
        }
        if ($runtimeStatus.decision_hash -ne $plan.decision_hash) {
            Fail 'persisted runtime session decision hash mismatch.'
        }
        if ($plan.runtime_contract_hash -and $runtimeStatus.contract_hash -ne $plan.runtime_contract_hash) {
            Fail 'persisted runtime session contract hash mismatch.'
        }
        if ($plan.session_state -ne 'RUNNING') {
            $persistedPlan = ConvertFrom-JsonCompatible -JsonText ($plan | ConvertTo-Json -Depth 50)
            $persistedPlan.status = 'SESSION_STARTED'
            $persistedPlan.session_state = 'RUNNING'
            $persistedPlan.runtime_contract_hash = $runtimeStatus.contract_hash
            Save-OperationalPlan -Plan $persistedPlan -Path $planPath
        }
        Write-Host ('Session already started: {0}' -f $plan.session_id)
        Write-Host '$env:PAPER_DATA_DIR = "C:\Users\Vitor\BotTraderPaperData"'
        Write-Host 'python bot_telegram.py'
        Write-Host 'Then, in the authorized Telegram chat, send /vigia.'
        Write-Host 'After a restart, run runtime resume and send /vigia again.'
        return
    }
    $binding = Invoke-PaperOperations @(
        'campaign', 'bind',
        '--campaign-id', $plan.campaign_id,
        '--decision-file', $plan.promotion_decision_path,
        '--campaign-db', (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'),
        '--data-dir', $PaperDataDir
    )
    $backupVerify = Invoke-PaperOperations @('backup', 'verify', '--backup-dir', $plan.backup_dir)
    $restoreVerify = Invoke-PaperOperations @('restore', 'verify', '--backup-dir', $plan.backup_dir)
    $doctorReport = Invoke-PaperOperations @('doctor', '--data-dir', $PaperDataDir)

    if ($doctorReport.status -ne 'READY') {
        Fail 'doctor is not ready.'
    }
    Assert-StrictBool -Value $doctorReport.local_operations_ready -Name 'doctor.local_operations_ready' -Expected:$true
    Assert-StrictBool -Value $doctorReport.bot_runtime_ready -Name 'doctor.bot_runtime_ready' -Expected:$true
    Assert-StrictBool -Value $backupVerify.verified -Name 'backup.verified' -Expected:$true
    Assert-StrictBool -Value $restoreVerify.verified -Name 'restore.verified' -Expected:$true
    Assert-PlanConsistency -Plan $plan -Reference $reference -Decision $decision -Cohort $cohort -Campaign $campaign -BackupVerify $backupVerify -RestoreVerify $restoreVerify -BindingHash $binding.binding_hash
    if ($plan.cohort_hash -ne $cohort.cohort_hash) { Fail 'cohort hash mismatch.' }
    if ($plan.campaign_hash -ne $campaign.campaign_hash) { Fail 'campaign hash mismatch.' }
    if ($plan.reference_hash -ne $reference.operational_provenance.reference_hash) { Fail 'reference hash mismatch.' }
    if ($plan.decision_hash -ne $decision.decision_hash) { Fail 'decision hash mismatch.' }

    $nowUtc = [datetime]::UtcNow
    $windowStartUtc = Convert-FromUtcIso $plan.window_start_utc
    $windowEndUtc = Convert-FromUtcIso $plan.window_end_utc
    if ($nowUtc -lt $windowStartUtc) {
        Fail 'campaign window has not started yet.'
    }
    if ($nowUtc -ge $windowEndUtc) {
        Fail 'campaign window has already ended.'
    }

    if ($plan.status -eq 'SESSION_STARTING') {
        $active = Get-ActiveRuntimeSession -DataDir $PaperDataDir
        if ($null -eq $active) {
            Fail 'session_starting state requires an active runtime session for recovery.'
        }
        if ($plan.session_id -and $plan.session_id -ne $active.session_id) {
            Fail 'active runtime session does not match the persisted plan.'
        }
        if ($plan.decision_hash -ne $active.decision_hash) {
            Fail 'active runtime session decision hash mismatch.'
        }
        if ($plan.runtime_contract_hash -and $plan.runtime_contract_hash -ne $active.contract_hash) {
            Fail 'active runtime session contract hash mismatch.'
        }
        $runtimeStatus = Invoke-PaperOperations @('session', 'status', '--session-id', $active.session_id, '--data-dir', $PaperDataDir)
        Assert-StringValue -Value $runtimeStatus.session_id -Name 'runtime session_id'
        if ($runtimeStatus.state -ne 'RUNNING') {
            Fail 'recovered runtime session is not running.'
        }
        if ($runtimeStatus.session_id -ne $active.session_id) {
            Fail 'recovered runtime session id mismatch.'
        }
        if ($runtimeStatus.decision_hash -ne $plan.decision_hash) {
            Fail 'recovered runtime session decision hash mismatch.'
        }
        if ($runtimeStatus.contract_hash -ne $active.contract_hash) {
            Fail 'recovered runtime session contract hash mismatch.'
        }
        $recoveredPlan = ConvertFrom-JsonCompatible -JsonText ($plan | ConvertTo-Json -Depth 50)
        $recoveredPlan.status = 'SESSION_STARTED'
        $recoveredPlan.session_id = $active.session_id
        $recoveredPlan.session_state = 'RUNNING'
        $recoveredPlan.runtime_contract_hash = $active.contract_hash
        Save-OperationalPlan -Plan $recoveredPlan -Path $planPath
        Write-Host ('Recovered active session {0}.' -f $active.session_id)
        return
    }

    if ($plan.status -ne 'PREPARED') {
        Fail 'operational plan must be PREPARED or SESSION_STARTING.'
    }

    $startingPlan = ConvertFrom-JsonCompatible -JsonText ($plan | ConvertTo-Json -Depth 50)
    $startingPlan.status = 'SESSION_STARTING'
    Save-OperationalPlan -Plan $startingPlan -Path $planPath

    try {
        $sessionStart = Invoke-PaperOperations @(
            'session', 'start',
            '--campaign-id', $plan.campaign_id,
            '--decision-file', $plan.promotion_decision_path,
            '--campaign-db', (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'),
            '--data-dir', $PaperDataDir
        )
        Assert-StringValue -Value $sessionStart.session_id -Name 'session_id'
        $sessionStatus = Invoke-PaperOperations @('session', 'status', '--session-id', $sessionStart.session_id, '--data-dir', $PaperDataDir)
        if ($sessionStatus.state -ne 'RUNNING') {
            Fail 'session start did not result in a running session.'
        }
        if ($sessionStatus.decision_hash -ne $plan.decision_hash) {
            Fail 'session start revalidation failed.'
        }
        if ($sessionStatus.contract_hash -ne $startingPlan.runtime_contract_hash -and $startingPlan.runtime_contract_hash) {
            Fail 'session start contract hash mismatch.'
        }
        $startedPlan = ConvertFrom-JsonCompatible -JsonText ($startingPlan | ConvertTo-Json -Depth 50)
        $startedPlan.status = 'SESSION_STARTED'
        $startedPlan.session_id = $sessionStart.session_id
        $startedPlan.session_state = $sessionStatus.state
        $startedPlan.runtime_contract_hash = $sessionStatus.contract_hash
        Save-OperationalPlan -Plan $startedPlan -Path $planPath
        Write-Host ('Session started successfully: {0}' -f $sessionStart.session_id)
        Write-Host '$env:PAPER_DATA_DIR = "C:\Users\Vitor\BotTraderPaperData"'
        Write-Host 'python bot_telegram.py'
        Write-Host 'Then, in the authorized Telegram chat, send /vigia.'
        Write-Host 'After a restart, run runtime resume and send /vigia again.'
    } catch {
        Write-Host 'SESSION_STARTING was persisted, but the final session start failed. Do not create another session automatically.'
        throw
    }
}

function Show-Review {
    $window = Get-CurrentWindow
    $windowStartUtc = Convert-ToUtcIso $window.start_utc
    $windowEndUtc = Convert-ToUtcIso $window.end_utc
    Write-Host 'Review mode: no commands will be executed.'
    Write-Host ''
    Write-Host 'Planned files:'
    Write-Host ('  {0}' -f (Join-Path $PaperDataDir 'reference.json'))
    Write-Host ('  {0}' -f (Join-Path $PaperDataDir 'promotion_decision.json'))
    Write-Host ('  {0}' -f (Join-Path $PaperDataDir 'operational-plan.json'))
    Write-Host ''
    Write-Host 'Commands that -Prepare will execute:'
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" initialize' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations phase5-reference --input "{1}"' -f $PythonExe, $ReferenceConfigFile)
    Write-Host ('  {0} -m paper_operations promotion-decision --reference-file "{1}" --policy-file "{2}"' -f $PythonExe, (Join-Path $PaperDataDir 'reference.json'), $PromotionPolicyFile)
    Write-Host ('  {0} -m paper_operations cohort prepare --strategy-version "{1}" --symbol "{2}" --interval "{3}" --inclusion-rule "sqlite_all_sessions" --period-start-utc "{4}" --period-end-utc "{5}" --runtime-db "{6}"' -f $PythonExe, $StrategyVersion, $Symbol, $Interval, $windowStartUtc, $windowEndUtc, (Join-Path $PaperDataDir 'paper_runtime.db'))
    Write-Host ('  {0} -m paper_operations campaign prepare --campaign-id "{1}" --policy-file "{2}" --reference-file "{3}" --strategy-version "{4}" --symbol "{5}" --interval "{6}" --inclusion-rule "sqlite_all_sessions" --period-start-utc "{7}" --period-end-utc "{8}" --cohort-hash "<cohort_hash>" --runtime-db "{9}" --campaign-db "{10}"' -f $PythonExe, $CampaignId, $CampaignPolicyFile, (Join-Path $PaperDataDir 'reference.json'), $StrategyVersion, $Symbol, $Interval, $windowStartUtc, $windowEndUtc, (Join-Path $PaperDataDir 'paper_runtime.db'), (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'))
    Write-Host ('  {0} -m paper_operations campaign bind --campaign-id "{1}" --decision-file "{2}" --campaign-db "{3}" --data-dir "{4}"' -f $PythonExe, $CampaignId, (Join-Path $PaperDataDir 'promotion_decision.json'), (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'), $PaperDataDir)
    Write-Host ('  {0} -m paper_operations backup create --data-dir "{1}" --backup-name "<timestamp>-campaign"' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations restore verify --backup-dir "<backup_dir>"' -f $PythonExe)
    Write-Host ('  {0} -m paper_operations doctor --data-dir "{1}"' -f $PythonExe, $PaperDataDir)
    Write-Host ''
    Write-Host 'Commands that -StartSession will execute:'
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" cohort status --runtime-db "{2}" --cohort-hash "<cohort_hash>"' -f $PythonExe, $PaperDataDir, (Join-Path $PaperDataDir 'paper_runtime.db'))
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" campaign status --campaign-id "{2}" --campaign-db "{3}"' -f $PythonExe, $PaperDataDir, $CampaignId, (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'))
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" campaign bind --campaign-id "{2}" --decision-file "{3}" --campaign-db "{4}"' -f $PythonExe, $PaperDataDir, $CampaignId, (Join-Path $PaperDataDir 'promotion_decision.json'), (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'))
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" backup verify --backup-dir "<backup_dir>"' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" restore verify --backup-dir "<backup_dir>"' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" doctor' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" session active' -f $PythonExe, $PaperDataDir)
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" session start --campaign-id "{2}" --decision-file "{3}" --campaign-db "{4}"' -f $PythonExe, $PaperDataDir, $CampaignId, (Join-Path $PaperDataDir 'promotion_decision.json'), (Join-Path $PaperDataDir 'paper_evaluation_campaign.db'))
    Write-Host ('  {0} -m paper_operations --data-dir "{1}" session status --session-id "<session_id>"' -f $PythonExe, $PaperDataDir)
    Write-Host ''
    Write-Host 'Blocking conditions:'
    Write-Host '  - promotion decision is not APPROVED_FOR_MONITORED_PAPER'
    Write-Host '  - missing or invalid plan schema'
    Write-Host '  - mismatched cohort, campaign, binding, reference, or decision hashes'
    Write-Host '  - backup/restore verification fails'
    Write-Host '  - doctor is not READY'
    Write-Host '  - current time is outside the campaign window'
    Write-Host '  - more than one active runtime session is found'
    Write-Host '  - recovery cannot determine the single active session unambiguously'
    Write-Host ''
    Write-Host 'No command has been executed.'
}

if ($Review) {
    Show-Review
    return
}

if ($Prepare) {
    Invoke-Prepare
    return
}

if ($StartSession) {
    Invoke-SessionStart
    return
}

Fail 'Specify one of -Review, -Prepare, or -StartSession.'
