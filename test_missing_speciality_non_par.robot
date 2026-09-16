*** Settings ***
Documentation       End-to-end negative validation for Practitioner Rule:
...                 MissingSpecialityCheckNonPAR
...                 BRP_0058
...
...                 Strategy:
...                 - Fetch a live practitioner/location with no active
...                   practitioner specialty and no Participating product.
...                 - Upload a Practitioner Bulk Update CSV.
...                 - Create a Non-Participating product.
...                 - Do not provide practitioner or product specialty fields.
...                 - Rule engine should fire:
...                   MissingSpecialityCheckNonPAR.
...
...                 Expected Error:
...                 Missing specialty for Non-PAR practitioner

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
# ─────────── Environment ───────────
${ENV}                      int

# ─────────── AWS ───────────
${S3_BUCKET}                usmg-${ENV}-provider-validation-service
${GLUE_JOB_NAME}            usmg-${ENV}-provider-validation-service-glue

# ─────────── File ───────────
${REPORTS_DIR}              ${EXECDIR}${/}configs${/}csv
${FILE_NAME}                Missing_Speciality_Non_PAR.csv
${UPLOAD_FILE_PATH}         ${REPORTS_DIR}${/}${FILE_NAME}

# ─────────── Waits ───────────
${S3_WAIT_TIMEOUT}          120
${S3_POLL_INTERVAL}         15

# ─────────── Process ───────────
${PROCESS_PRACTITIONER}     Practitioner Bulk Update

# ─────────── Rule ───────────
${RULE_NAME}                MissingSpecialityCheckNonPAR
${EXPECTED_ERROR_MSG}       Missing specialty for Non-PAR practitioner


*** Test Cases ***
E2E Workflow For MissingSpecialityCheckNonPAR Rule
    [Tags]    regression    negative    practitioner    BRP_0058
    ...    MissingSpecialityCheckNonPAR
    ${PROCESS_PRACTITIONER}


*** Keywords ***
# ═══════════════════════════════════════════════════════════════════
# MAIN WORKFLOW
# ═══════════════════════════════════════════════════════════════════
Execute Data Remediation E2E Workflow
    [Documentation]    Uploads negative test CSV and validates BRP_0058.
    [Arguments]    ${process_name}

    ${tracking_no}=    Upload File And Get Tracking Number
    ...    ${process_name}

    Verify File Is In Pending Status
    ...    ${process_name}
    ...    ${tracking_no}

    ${s3_keys}=    Get And Store S3 Keys For Process
    ...    ${process_name}

    Validate File In S3 Upload Prefix
    ...    ${s3_keys}[upload]

    Approve And Track File
    ...    ${tracking_no}

    ${process_id_db}=    Verify Final Processed Status
    ...    ${tracking_no}
    ...    ${process_name}

    Validate MissingSpecialityCheckNonPAR Rule Fired
    ...    ${process_id_db}


# ═══════════════════════════════════════════════════════════════════
# SUITE SETUP / TEARDOWN
# ═══════════════════════════════════════════════════════════════════
Setup Data Remediation Suite
    Open Browser For Environment    ${ENV}

    IF    '${ENV}' == 'int'
        Login To Application    ${USERNAME}    ${PASSWORD}
    ELSE IF    '${ENV}' == 'pvs'
        Login To Application Without MFA    ${USERNAME}    ${PASSWORD}
    ELSE
        Fail    Unsupported environment: ${ENV}
    END

    Click On Data Remediation Link


Teardown Data Remediation Suite
    Close Browser
    Remove Directory
    ...    ${REPORTS_DIR}
    ...    recursive=${True}


Reset Page State
    Sleep    2s
    Reload Page
    Navigate To Home Page
    Click On Data Remediation Link


# ═══════════════════════════════════════════════════════════════════
# FILE CREATION / UPLOAD
# ═══════════════════════════════════════════════════════════════════
Upload File And Get Tracking Number
    [Documentation]    Fetches live Non-PAR/no-specialty data and creates
    ...                a CSV that should trigger BRP_0058.
    [Arguments]    ${process_name}

    &{test_data}=    Get Missing Speciality Non Par Violation Data

    Log    ✅ BRP_0058 violation data selected:
    Log    PractitionerID=${test_data}[PractitionerID]
    Log    NPI=${test_data}[NationalProviderID]
    Log    Practice TIN=${test_data}[PracticeTaxIDNumber]
    Log    Location TIN=${test_data}[TaxIDNumber]
    Log    Group NPI=${test_data}[ServiceGroupNationalProviderID]
    Log    Location=${test_data}[ServiceLocationName]

    Capture Upload Start Time
    Select Process From Dropdown
    ...    ${process_name}

    ${tracking_no}=    Get Random Six Digit Number
    Log    📋 Tracking Number: ${tracking_no}

    Enter Text Into Tracking Number
    ...    ${tracking_no}

    &{practitioner_overrides}=    Create Dictionary
    # ─── Existing practitioner selected by DB query ───
    ...    NationalProviderID=${test_data}[NationalProviderID]
    ...    FirstName=Negative
    ...    LastName=MissingSpecialityNonPAR
    ...    MiddleName=Test
    ...    GenderName=male
    ...    BirthDate=1990-01-01
    ...    PractitionerTypeName=Medical Doctor (MD)
    ...    StatusTypeName=Active
    ...    StatusEffectiveDate=2024-01-01
    ...    NonCredentialed=N
    ...    ActiveMilitaryOrReserve=N

    # ─── Practice / Group ───
    ...    GroupTaxIDNumber=${test_data}[PracticeTaxIDNumber]
    ...    GroupNationalProviderID=${test_data}[ServiceGroupNationalProviderID]
    ...    TaxIDNumber=${test_data}[TaxIDNumber]
    ...    PracticeName=${test_data}[PracticeName]
    ...    PracticeTypeName=${test_data}[PracticeTypeName]
    ...    PracticeNotes=Negative test - MissingSpecialityCheckNonPAR BRP_0058

    # ─── Active Service Location ───
    ...    ServiceGroupNationalProviderID=${test_data}[ServiceGroupNationalProviderID]
    ...    ServiceLocationname=${test_data}[ServiceLocationName]
    ...    ServiceLineNumber1=${test_data}[ServiceLineNumber1]
    ...    ServiceCity=${test_data}[ServiceCity]
    ...    ServiceCounty=${test_data}[ServiceCounty]
    ...    ServiceState=${test_data}[ServiceState]
    ...    ServiceZipCode=${test_data}[ServiceZipCode]
    ...    ServiceCountryCode=${test_data}[ServiceCountryCode]
    ...    ServiceLocationDateFrom=${test_data}[ServiceLocationDateFrom]
    ...    ServiceInDirectory=Y
    ...    PrimaryLocation=Y

    # ─── Non-PAR Product ───
    ...    ProductName=A001 - Non Par Network
    ...    ProductTypeName=HMO IPA MEDICARE
    ...    ProductDateFrom=2024-01-01
    ...    ProductPopulationName=STANDARD
    ...    ProductStatusTypeName=Non-Participating
    ...    ProductContractName=A001
    ...    ProductArchived=N

    # ─── Intentionally blank specialty fields ───
    # This is the actual BRP_0058 negative condition.
    ...    PractitionerSpecialtyName=${EMPTY}
    ...    PractitionerSpcPrimarySpecialty=${EMPTY}
    ...    PractitionerSpcBoardCertified=${EMPTY}
    ...    PractitionerSpcArchived=${EMPTY}

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

    Select Template For Bulk Update
    ...    ${process_name}

    Upload File PDM
    ...    ${UPLOAD_FILE_PATH}
    ...    ${FILE_NAME}

    Verify Successful Message
    ...    ${MSG_UPLOAD_SUCCESS}

    Log    ✅ File uploaded with tracking number: ${tracking_no}
    RETURN    ${tracking_no}


# ═══════════════════════════════════════════════════════════════════
# STATUS / S3
# ═══════════════════════════════════════════════════════════════════
Verify File Is In Pending Status
    [Arguments]    ${process_name}    ${tracking_no}

    Navigate To Review Tab And Search
    ...    ${process_name}
    ...    ${tracking_no}

    Verify File Status
    ...    ${tracking_no}
    ...    ${STATUS_PENDING}


Get And Store S3 Keys For Process
    [Arguments]    ${process_name}

    ${upload_key}    ${approved_key}    ${processed_key}=
    ...    Get S3 Keys For Process For E2E
    ...    ${process_name}

    &{s3_keys}=    Create Dictionary
    ...    upload=${upload_key}
    ...    approved=${approved_key}
    ...    processed=${processed_key}

    RETURN    ${s3_keys}


Validate File In S3 Upload Prefix
    [Arguments]    ${upload_key}

    Wait For Our File To Appear In S3
    ...    ${FILE_NAME}
    ...    bucket=${S3_BUCKET}
    ...    prefix=${upload_key}
    ...    timeout=${S3_WAIT_TIMEOUT}
    ...    interval=${S3_POLL_INTERVAL}


Approve And Track File
    [Arguments]    ${tracking_no}

    Capture Upload Start Time
    Approve The File
    ...    ${tracking_no}


Verify Final Processed Status
    [Arguments]    ${tracking_no}    ${process_name}

    ${process_id_db}=    Handle Queued Status If Present
    ...    ${tracking_no}
    ...    ${process_name}

    Verify File Status
    ...    ${tracking_no}
    ...    ${STATUS_QUEUED}

    RETURN    ${process_id_db}


# ═══════════════════════════════════════════════════════════════════
# RULE VALIDATION
# ═══════════════════════════════════════════════════════════════════
Validate MissingSpecialityCheckNonPAR Rule Fired
    [Documentation]    Verifies BRP_0058 returned Error with expected message.
    [Arguments]    ${process_id_db}

    Wait For DB Sync

    Verify Rules By Rule Name
    ...    ${RULE_NAME}
    ...    ${process_id_db}
    ...    ${EXPECTED_ERROR_MSG}

    Log    ✅ Rule ${RULE_NAME} fired successfully:
    ...    ${EXPECTED_ERROR_MSG}
