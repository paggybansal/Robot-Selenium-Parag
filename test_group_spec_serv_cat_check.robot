*** Settings ***
Documentation       End-to-end negative validation for Practice Rule:
...                 GroupSpecServCatCheck
...                 ("Group specialty/service category mismatch")
...
...                 Strategy:
...                 - Fetch an active Practice's NPI+TIN from live DB.
...                 - Upload a CSV where the Billing Service Category details
...                   are intentionally incompatible:
...                     • BillingServiceTypeName = Dentistry
...                     • BillingServiceCategoryTypeName = Cardiology
...                 - Rule engine should detect the mismatch and fire BRG_0003.

Resource            ../../../resources/base/base_setup.resource
Resource            ../../../resources/pages/login_page.resource
Resource            ../../../resources/pages/home_page.resource
Resource            ../../../resources/pages/data_remediation_page.resource
Resource            ../../../resources/keywords/aws_s3.resource
Resource            ../../../resources/keywords/aws_glue.resource
Resource            ../../../resources/keywords/wait_utils.resource
Resource            ../../../resources/keywords/pdqa_db_validation_keyword.resource
Library             ../../../db_queries/pdqa_db_queries.py
Variables           ../../../resources/constants/constants.py

Suite Setup         Setup Data Remediation Suite
Suite Teardown      Teardown Data Remediation Suite
Test Setup          Reset Page State
Test Teardown       Run Keyword If Test Failed    Capture Page Screenshot

Test Template       Execute Data Remediation E2E Workflow


*** Variables ***
# ─────────── AWS Configuration ───────────
${ENV}                      int
${S3_BUCKET}                usmg-${ENV}-provider-validation-service
${GLUE_JOB_NAME}            usmg-${ENV}-provider-validation-service-glue

# ─────────── File Configuration ───────────
${REPORTS_DIR}              ${EXECDIR}${/}configs${/}csv
${FILE_NAME}                Bulk_Update_Automation.csv
${UPLOAD_FILE_PATH}         ${REPORTS_DIR}${/}${FILE_NAME}

# ─────────── Timeouts ───────────
${S3_WAIT_TIMEOUT}          120
${S3_POLL_INTERVAL}         15

# ─────────── Process Names ───────────
${PROCESS_PRACTICE}         Practice Bulk Update

# ─────────── Rule Config ───────────
${RULE_NAME}                GroupSpecServCatCheck
${EXPECTED_ERROR_MSG}       Group specialty/service category mismatch


*** Test Cases ***                                                            PROCESS_NAME
E2E Workflow For Practice Rule GroupSpecServCatCheck Validation               ${PROCESS_PRACTICE}
    [Tags]    regression    negative    GroupSpecServCatCheck    practice    BRG_0003


*** Keywords ***
# ═══════════════════════════════════════════════════════════════════
# MAIN TEST TEMPLATE
# ═══════════════════════════════════════════════════════════════════
Execute Data Remediation E2E Workflow
    [Documentation]    End-to-end workflow: Upload → Pending → Approve →
    ...                Processed → S3 Validation → Rule Validation.
    [Arguments]    ${process_name}

    ${tracking_no}=          Upload File And Get Tracking Number    ${process_name}
    Verify File Is In Pending Status                                ${process_name}    ${tracking_no}

    ${s3_keys}=              Get And Store S3 Keys For Process      ${process_name}
    Validate File In S3 Upload Prefix                               ${s3_keys}[upload]

    ${process_id}=           Get Process Id From S3                 ${s3_keys}[upload]
    Approve And Track File                                          ${tracking_no}

    ${process_id_db}    Verify Final Processed Status               ${tracking_no}    ${process_name}
    Validate GroupSpecServCatCheck Rule Fired                      ${process_id_db}


# ═══════════════════════════════════════════════════════════════════
# SUITE LIFECYCLE
# ═══════════════════════════════════════════════════════════════════
Setup Data Remediation Suite
    [Documentation]    Opens browser, logs in, and navigates to Data Remediation page.
    Open Browser For Environment    ${ENV}
    IF    '${ENV}' == 'int'
        Login To Application                ${USERNAME}    ${PASSWORD}
    ELSE IF    '${ENV}' == 'pvs'
        Login To Application Without MFA    ${USERNAME}    ${PASSWORD}
    ELSE
        Fail    Unsupported environment.
    END
    Click On Data Remediation Link
	
Teardown Data Remediation Suite
    [Documentation]    Closes browser and removes generated CSV files.
    Close Browser
    Remove Directory    ${REPORTS_DIR}    recursive=${True}

Reset Page State
    [Documentation]    Allows DOM to settle between tests and returns to Data Remediation page.
    Sleep    2s
    Reload Page
    Navigate To Home Page
    Click On Data Remediation Link


# ═══════════════════════════════════════════════════════════════════
# WORKFLOW STEPS
# ═══════════════════════════════════════════════════════════════════
Upload File And Get Tracking Number
    [Documentation]    Creates practice CSV that will trigger
    ...                GroupSpecServCatCheck rule by intentionally pairing
    ...                incompatible specialty classifications.
    [Arguments]    ${process_name}

    # ═══════════════════════════════════════════════════════════════
    # 🎯 FETCH LIVE DATA FROM SYMPLR DB
    # ═══════════════════════════════════════════════════════════════
    &{test_data}=    Get Group Spec Serv Cat Check Violation Data
    Log    ✅ Live Practice Data: NPI=${test_data}[GroupNationalProviderID] TIN=${test_data}[PracticeTaxIDNumber]

    Capture Upload Start Time
    Select Process From Dropdown    ${process_name}

    ${tracking_no}=    Get Random Six Digit Number
    Log    📋 Tracking Number: ${tracking_no}
    Enter Text Into Tracking Number    ${tracking_no}

    # ═══════════════════════════════════════════════════════════════
    # 🎯 CREATE PRACTICE CSV WITH MISMATCH
    # 🔴 KEY: BillingServiceTypeName does not match BillingServiceCategoryTypeName
    # ═══════════════════════════════════════════════════════════════
    &{practice_overrides}=    Create Dictionary
    # ─── Practice Core ───
    ...    NationalProviderID=${test_data}[GroupNationalProviderID]
    ...    TaxIDNumber=${test_data}[PracticeTaxIDNumber]
    ...    PracticeName=${test_data}[PracticeName]
    ...    PracticeTypeName=${test_data}[PracticeTypeName]
    ...    Notes=Negative test - GroupSpecServCatCheck (env: ${ENV}, live DB)
    ...    ElectronicBillingCapability=N
    # ─── Billing Address ───
    ...    BillingLineNumber1=44567 MCINTOSH CIR # 12519-316
    ...    BillingLocationName=Mismatched Billing Location
    ...    BillingDateFrom=2024-01-01
    ...    BillingCity=SUWANEE
    ...    BillingCounty=GWINNETT
    ...    BillingState=GA
    ...    BillingZipCode=30024
    ...    BillingCountryCode=US
    # ─── Service Address ───
    ...    ServiceLineNumber1=535 E 70th St
    ...    ServiceLocationName=Mismatched Service Location
    ...    ServiceLegalName=Mismatched Service Legal
    ...    ServiceDateFrom=2024-01-01
    ...    ServiceCity=NEW YORK
    ...    ServiceCounty=NEW YORK
    ...    ServiceState=NY
    ...    ServiceZipCode=10021
    ...    ServiceCountryCode=US
    # ─── Billing Service Category (MISMATCH TRIGGERED HERE) ───
    ...    BillingServiceTypeName=${test_data}[MismatchedServiceTypeName]             # Dentistry
    ...    BillingServiceCategoryTypeName=${test_data}[MismatchedSpecialtyCategoryName]  # Cardiology
    # ─── Product ───
    ...    ProductName=102YX - S FL MA HMO Independent NonPrac Network
    ...    ProductDateFrom=2026-06-05
    ...    ProductStatusTypeName=Participating
    ...    ProductContractName=FLDSNP
    ...    ProductPopulationName=MEDICAID
    ...    ProductStatusEffectiveDate=2024-10-10
    ...    ProductTypeName=HMO Medicare

    ${path}=    Create Practice CSV
    ...    file_path=${UPLOAD_FILE_PATH}
    ...    npi=${test_data}[GroupNationalProviderID]
    ...    tax_id=${test_data}[PracticeTaxIDNumber]
    ...    mode=baseline
    ...    &{practice_overrides}

    Select Template For Bulk Update    ${process_name}
    Upload File PDM                    ${UPLOAD_FILE_PATH}    ${FILE_NAME}
    Verify Successful Message          ${MSG_UPLOAD_SUCCESS}

    Log    ✅ File uploaded with tracking number: ${tracking_no}
    RETURN    ${tracking_no}

Verify File Is In Pending Status
    [Documentation]    Navigates to the Review tab and verifies file is in PENDING status.
    [Arguments]    ${process_name}    ${tracking_no}
    Navigate To Review Tab And Search    ${process_name}    ${tracking_no}
    Verify File Status                   ${tracking_no}    ${STATUS_PENDING}

Get And Store S3 Keys For Process
    [Documentation]    Retrieves S3 keys for upload, approved, and processed prefixes.
    [Arguments]    ${process_name}
    ${upload_key}    ${approved_key}    ${processed_key}=
    ...    Get S3 Keys For Process For E2E    ${process_name}
    &{s3_keys}=    Create Dictionary
    ...    upload=${upload_key}
    ...    approved=${approved_key}
    ...    processed=${processed_key}
    RETURN    ${s3_keys}
	
Validate File In S3 Upload Prefix
    [Documentation]    Waits for the file to land in the S3 upload prefix.
    [Arguments]    ${upload_key}
    Wait For Our File To Appear In S3
    ...    ${FILE_NAME}
    ...    bucket=${S3_BUCKET}
    ...    prefix=${upload_key}
    ...    timeout=${S3_WAIT_TIMEOUT}
    ...    interval=${S3_POLL_INTERVAL}

Get Process Id From S3
    [Documentation]    Validates the uploaded file in S3 and returns the process ID.
    [Arguments]    ${upload_key}
    ${process_id}=    Validate S3 Upload And Get Process Id
    ...    ${FILE_NAME}    ${S3_BUCKET}    ${upload_key}
    Log    ✅ Retrieved Process ID: ${process_id}
    RETURN    ${process_id}

Approve And Track File
    [Documentation]    Captures upload time and approves the uploaded file.
    [Arguments]    ${tracking_no}
    Capture Upload Start Time
    Approve The File    ${tracking_no}

Validate File Movement To Approved
    [Documentation]    Waits for the file to move to the approved prefix and returns process ID.
    [Arguments]    ${approved_key}
    Wait For Our File To Appear In S3
    ...    ${FILE_NAME}
    ...    bucket=${S3_BUCKET}
    ...    prefix=${approved_key}
    ...    timeout=${S3_WAIT_TIMEOUT}
    ...    interval=${S3_POLL_INTERVAL}
    ${process_id_db}=    Validate S3 Upload And Get Process Id
    ...    ${FILE_NAME}    ${S3_BUCKET}    ${approved_key}
    RETURN    ${process_id_db}

Verify Final Processed Status
    [Documentation]    Handles queued state and verifies file is in PROCESSED status.
    [Arguments]    ${tracking_no}    ${process_name}
    ${process_id_db}    Handle Queued Status If Present    ${tracking_no}    ${process_name}
    Verify File Status                 ${tracking_no}    ${STATUS_QUEUED}
    RETURN    ${process_id_db}


# ═══════════════════════════════════════════════════════════════════
# RULE VALIDATION
# ═══════════════════════════════════════════════════════════════════
Validate GroupSpecServCatCheck Rule Fired
    [Documentation]    Waits for DB sync and validates that the
    ...                GroupSpecServCatCheck rule fired
    ...                with the expected error message.
    [Arguments]    ${process_id_db}
    Wait For DB Sync
    Verify Rules By Rule Name    ${RULE_NAME}    ${process_id_db}    ${EXPECTED_ERROR_MSG}
    Log    ✅ Rule ${RULE_NAME} fired successfully
