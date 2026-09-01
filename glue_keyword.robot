*** Settings ***
Library     ../libraries/GlueBotoLibrary.py    profile_name=${AWS_PROFILE}    region_name=${AWS_REGION}
...         WITH NAME    Glue
Library     Collections

*** Variables ***
${AWS_PROFILE}          ${EMPTY}
${AWS_REGION}           us-east-1
${GLUE_TIMEOUT_SEC}     1200
${GLUE_POLL_SEC}        30

*** Keywords ***
Trigger Glue Job With Parameters
    [Documentation]    Triggers a Glue job with parameters and returns the RunId.
    [Arguments]    ${job_name}    ${parameters}
    ${run_id}=    Glue.Trigger Glue Job    ${job_name}    ${parameters}
    Should Not Be Empty    ${run_id}    Glue trigger did not return a RunId
    Log    Triggered '${job_name}' → RunId: ${run_id}    console=True
    RETURN    ${run_id}

Trigger Glue Job And Verify Success
    [Documentation]    Trigger → wait (existing keyword) → assert SUCCEEDED (existing keyword).
    [Arguments]    ${job_name}    ${parameters}
    ...            ${timeout_seconds}=${GLUE_TIMEOUT_SEC}    ${poll_interval}=${GLUE_POLL_SEC}
    ${run_id}=    Trigger Glue Job With Parameters    ${job_name}    ${parameters}
    ${status}=    Glue.Wait For Glue Job Completion    ${job_name}    ${run_id}
    ...           timeout_seconds=${timeout_seconds}    poll_interval=${poll_interval}
    Glue.Glue Job Run Should Have Succeeded    ${job_name}    ${run_id}
    RETURN    ${run_id}

Trigger Glue Job And Verify Failure
    [Documentation]    Negative-flow: job is expected to FAIL; returns the Glue error message.
    [Arguments]    ${job_name}    ${parameters}
    ...            ${timeout_seconds}=${GLUE_TIMEOUT_SEC}    ${poll_interval}=${GLUE_POLL_SEC}
    ${run_id}=    Trigger Glue Job With Parameters    ${job_name}    ${parameters}
    ${status}=    Glue.Wait For Glue Job Completion    ${job_name}    ${run_id}
    ...           timeout_seconds=${timeout_seconds}    poll_interval=${poll_interval}
    Should Be Equal    ${status}    FAILED
    ${error}=    Glue.Get Glue Job Error Message    ${job_name}    ${run_id}
    RETURN    ${error}
