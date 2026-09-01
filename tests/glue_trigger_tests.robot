*** Settings ***
Library           Collections
Library           DateTime
Resource          ../resources/glue_keywords.robot
Force Tags        glue    integration

*** Variables ***
${JOB_NAME}       my-split-job
${SOURCE_PATH}    s3://qa-data-bucket/input/customers/
${TARGET_PATH}    s3://qa-data-bucket/output/customers/

*** Test Cases ***
TC01 - Trigger Glue Job With Dictionary Parameters And Verify Success
    [Documentation]    Happy path: dictionary params, wait via existing keyword, assert success + params.
    ${params}=    Create Dictionary
    ...    --source_path=${SOURCE_PATH}
    ...    --target_path=${TARGET_PATH}
    ...    --env=qa
    ...    --load_type=full
    ${run_id}=    Trigger Glue Job And Verify Success    ${JOB_NAME}    ${params}
    Glue.Glue Job Run Should Have Arguments    ${JOB_NAME}    ${run_id}    ${params}

TC02 - Trigger Glue Job With Inline Parameters
    [Documentation]    '--' prefix optional; library normalizes keys before calling Glue.
    ${run_id}=    Glue.Trigger Glue Job    ${JOB_NAME}
    ...    source_path=${SOURCE_PATH}    target_path=${TARGET_PATH}    env=qa
    ${status}=    Glue.Wait For Glue Job Completion    ${JOB_NAME}    ${run_id}
    ...    timeout_seconds=900    poll_interval=30
    Should Be Equal    ${status}    SUCCEEDED
    Glue.Glue Job Run Should Have Arguments    ${JOB_NAME}    ${run_id}    env=qa

TC03 - Trigger Glue Job With JSON String Parameters
    ${json_params}=    Set Variable    {"--env":"qa","--load_type":"delta","--batch_size":"5000"}
    ${run_id}=    Glue.Trigger Glue Job    ${JOB_NAME}    ${json_params}
    ${run}=       Glue.Get Glue Job Run Details    ${JOB_NAME}    ${run_id}
    Should Be Equal    ${run}[Arguments][--batch_size]    5000

TC04 - Trigger And Wait In One Step With Capacity Override
    ${params}=    Create Dictionary    --env=qa    --load_type=full
    ${run}=       Glue.Trigger Glue Job And Wait For Completion    ${JOB_NAME}    ${params}
    ...           timeout_seconds=1500    poll_interval=30
    ...           worker_type=G.1X    number_of_workers=5
    Should Be Equal    ${run}[JobRunState]         SUCCEEDED
    Should Be True     ${run}[ExecutionTime] > 0
    Log                Run: ${run}[RunId] | ${run}[ExecutionTime]s    console=True

TC05 - Trigger Glue Job Without Parameters
    [Documentation]    Job with no runtime arguments must still start.
    ${run_id}=    Glue.Trigger Glue Job    ${JOB_NAME}
    Should Not Be Empty    ${run_id}

TC06 - Trigger Non Existent Glue Job Should Fail
    Run Keyword And Expect Error    *EntityNotFound*
    ...    Glue.Trigger Glue Job    non-existent-job-name

TC07 - Reserved Parameter Should Be Rejected Before AWS Call
    Run Keyword And Expect Error    *reserved AWS Glue argument*
    ...    Glue.Trigger Glue Job    ${JOB_NAME}    --JOB_NAME=hack

TC08 - Invalid Parameter Format Should Fail Fast
    Run Keyword And Expect Error    *Expected format: --key=value*
    ...    Glue.Trigger Glue Job    ${JOB_NAME}    --env

TC09 - Triggered Run Is Visible To Existing Verification Keywords
    [Documentation]    Integration check: new trigger + your existing time-window keywords.
    ${before}=    Get Current Date    time_zone=UTC    result_format=%Y-%m-%dT%H:%M:%S
    ${run_id}=    Glue.Trigger Glue Job    ${JOB_NAME}    --env=qa
    ${run}=       Glue.Get Glue Job Run After Time    ${JOB_NAME}    ${before}
    Should Not Be Equal    ${run}    ${None}
    Should Be Equal        ${run}[RunId]    ${run_id}
    ${status}=    Glue.Wait For Glue Job Completion    ${JOB_NAME}    ${run_id}
    ...    timeout_seconds=900    poll_interval=30
    ${verified}=  Glue.Verify Glue Job Ran After    ${JOB_NAME}    ${before}    SUCCEEDED
    Should Be Equal    ${verified}[run_id]    ${run_id}
