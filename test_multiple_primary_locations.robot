*** Settings ***
Documentation       End-to-end negative validation for Practitioner Rule:
...                 MultiplePrimaryLocations
...                 ("Multiple Primary Locations exists")
...
...                 Strategy:
...                 - Fetch live practitioner data from Symplr where the practitioner
...                   already has more than one active primary Service location for
...                   the same Practice Tax ID and Group NPI.
...                 - Upload a Practitioner Bulk Update CSV using this violating NPI.
...                 - Rule engine should detect multiple active primary locations
...                   and fire BRP_0022 / MultiplePrimaryLocations.
...
...                 Note:
...                 This test relies on violation data pre-existing in Symplr DB.
...                 Do NOT generate a new NPI for this test.

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
${PROCESS_PRACTITIONER}     Practitioner Bulk Update

# ─────────── Rule Config ───────────
${RULE_NAME}                MultiplePrimaryLocations
${EXPECTED_ERROR_MSG}       Multiple Primary Locations exists


*** Test Cases ***                                                                  PROCESS_NAME
E2E Workflow For Practitioner Rule MultiplePrimaryLocations Validation               ${PROCESS_PRACTITIONER}
    [Tags]    regression    negative    MultiplePrimaryLocations    practitioner    BRP_0022


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

    ${process_id_db}=        Verify Final Processed Status          ${tracking_no}    ${process_name}
    Validate MultiplePrimaryLocations Rule Fired                    ${process_id_db}


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
        Fail    Unsupported environment: ${ENV}
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
    [Documentation]    Creates practitioner CSV that should trigger
    ...                MultiplePrimaryLocations rule:
    ...                - Same practitioner already has more than one active
    ...                  primary Service location for same TIN and Group NPI.
    [Arguments]    ${process_name}

    # ═══════════════════════════════════════════════════════════════
    # FETCH LIVE VIOLATION DATA FROM SYMPLR DB
    # Do NOT generate a new NPI for this negative test.
    # We need an existing NPI that already satisfies count(*) > 1.
    # ═══════════════════════════════════════════════════════════════
    &{test_data}=    Get Multiple Primary Locations Violation Data

    Log    ✅ Live violation data:
    Log    NPI=${test_data}[NationalProviderID]
    Log    TIN=${test_data}[PracticeTaxIDNumber]
    Log    GroupNPI=${test_data}[ServiceGroupNationalProviderID]
    Log    PrimaryLocationCount=${test_data}[PrimaryLocationCount]

    Capture Upload Start Time
    Select Process From Dropdown    ${process_name}

    ${tracking_no}=    Get Random Six Digit Number
    Log    📋 Tracking Number: ${tracking_no}
    Enter Text Into Tracking Number    ${tracking_no}

    # ═══════════════════════════════════════════════════════════════
    # CREATE PRACTITIONER CSV WITH VIOLATION SETUP
    # The NPI comes from DB and already has multiple primary locations.
    # CSV reinforces same practitioner/group/location state.
    # ═══════════════════════════════════════════════════════════════
    &{practitioner_overrides}=    Create Dictionary
    # ─── Practitioner Core ───
    ...    NationalProviderID=${test_data}[NationalProviderID]
    ...    FirstName=${test_data}[FirstName]
    ...    LastName=${test_data}[LastName]
    ...    MiddleName=${test_data}[MiddleName]
    ...    GenderName=male
    ...    BirthDate=1990-01-01
    ...    PractitionerTypeName=Medical Doctor (MD)
    ...    StatusTypeName=Active
    ...    StatusEffectiveDate=2024-01-01
    ...    NonCredentialed=N
    ...    ActiveMilitaryOrReserve=Y
    # ─── Practice / Group ───
    ...    GroupTaxIDNumber=${test_data}[PracticeTaxIDNumber]
    ...    GroupNationalProviderID=${test_data}[ServiceGroupNationalProviderID]
    ...    TaxIDNumber=${test_data}[PracticeTaxIDNumber]
    ...    PracticeName=${test_data}[PracticeName]
    ...    PracticeTypeName=${test_data}[PracticeTypeName]
    ...    PracticeNotes=Negative test - MultiplePrimaryLocations BRP_0022
    # ─── Service Location ───
    ...    ServiceGroupNationalProviderID=${test_data}[ServiceGroupNationalProviderID]
    ...    ServiceLocationname=${test_data}[ServiceLocationName]
    ...    PrimaryLocation=Y
    ...    ServiceLineNumber1=${test_data}[ServiceLineNumber1]
    ...    ServiceCity=${test_data}[ServiceCity]
    ...    ServiceCounty=${test_data}[ServiceCounty]
    ...    ServiceState=${test_data}[ServiceState]
    ...    ServiceZipCode=${test_data}[ServiceZipCode]
    ...    ServiceCountryCode=${test_data}[ServiceCountryCode]
    ...    ServiceLocationDateFrom=2024-01-01
    ...    ServiceInDirectory=Y
    # ─── Keep product blank/minimal for location rule negative test ───
    ...    ProductName=${EMPTY}
    ...    ProductTypeName=${EMPTY}
    ...    ProductDateFrom=${EMPTY}
    ...    ProductPopulationName=${EMPTY}
    ...    ProductStatusTypeName=${EMPTY}
    ...    ProductContractName=${EMPTY}
    ...    ProductArchived=${EMPTY}
    ...    ProductSpecialtyName=${EMPTY}
    ...    ProductSpecialtyPanelStatusTypeName=${EMPTY}
    ...    ProductSpecialtyTypeName=${EMPTY}
    ...    ProductSpecialtyDateFrom=${EMPTY}
    ...    ProductSpecialtyInDirectory=${EMPTY}
    ...    ProductSpecialtyArchived=${EMPTY}

    ${path}=    Create Practitioner Integration CSV
    ...    file_path=${UPLOAD_FILE_PATH}
    ...    npi=${test_data}[NationalProviderID]
    ...    mode=baseline
    ...    &{practitioner_overrides}

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
    [Documentation]    Handles queued state and verifies file is in processed/queued state.
    [Arguments]    ${tracking_no}    ${process_name}
    ${process_id_db}=    Handle Queued Status If Present    ${tracking_no}    ${process_name}
    Verify File Status    ${tracking_no}    ${STATUS_QUEUED}
    RETURN    ${process_id_db}


# ═══════════════════════════════════════════════════════════════════
# RULE VALIDATION
# ═══════════════════════════════════════════════════════════════════
Validate MultiplePrimaryLocations Rule Fired
    [Documentation]    Waits for DB sync and validates that the
    ...                MultiplePrimaryLocations rule fired
    ...                with the expected error message.
    [Arguments]    ${process_id_db}

    Wait For DB Sync
    Verify Rules By Rule Name    ${RULE_NAME}    ${process_id_db}    ${EXPECTED_ERROR_MSG}
    Log    ✅ Rule ${RULE_NAME} fired successfully
