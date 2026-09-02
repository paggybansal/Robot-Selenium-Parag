*** Settings ***
Resource          ../resources/excel_keywords.robot
Force Tags        excel    data-validation

*** Test Cases ***
TC01 - Read Excel File With Headers As Keys
    [Documentation]    Excel → pandas → list of dictionaries keyed by header names.
    ${rows}=      Load Excel As Dictionaries
    ${headers}=   Excel.Get Excel Headers    ${EXCEL_FILE}
    Log List      ${headers}
    Dictionary Should Contain Key    ${rows}[0]    ${TYPE_COLUMN}

TC02 - Type Column Should Be 1 In Every Row
    [Documentation]    Main requirement — fails with row numbers + actual values.
    Verify Type Column Is Always One

TC03 - Type Column Should Be 1 Using Pre Loaded Rows
    [Documentation]    Read once, assert many times (faster for big files).
    ${rows}=    Load Excel As Dictionaries
    Excel.Excel Column Values Should Be    ${rows}    ${TYPE_COLUMN}    1
    Excel.Excel Should Contain Columns     ${rows}    ${TYPE_COLUMN}

TC04 - Type Column Should Have Only Allowed Values
    ${allowed}=    Create List    1
    Excel.Excel Column Values Should Be In    ${EXCEL_FILE}    ${TYPE_COLUMN}    ${allowed}

TC05 - Row Level Check Using Pandas Dataframe
    [Documentation]    Use the DataFrame when you need pandas operations.
    ${df}=       Excel.Read Excel File As Dataframe    ${EXCEL_FILE}
    ${values}=   Excel.Get Excel Column Values    ${df}    ${TYPE_COLUMN}    unique=True
    Length Should Be    ${values}    1
    Should Be Equal As Numbers    ${values}[0]    1

TC06 - Save Parsed Data As Evidence
    ${rows}=    Load Excel As Dictionaries
    ${json}=    Excel.Save Excel Data As Json    ${rows}    ${OUTPUT DIR}${/}evidence${/}excel_rows.json
    File Should Exist    ${json}

TC07 - Missing Column Should Fail Clearly
    [Tags]    negative
    Run Keyword And Expect Error    *not found*
    ...    Excel.Excel Column Values Should Be    ${EXCEL_FILE}    non_existing_col    1

TC08 - Wrong Type Value Should Report Excel Row Numbers
    [Documentation]    Negative: verifies our failure message quality.
    [Tags]    negative
    Run Keyword And Expect Error    *Excel row*
    ...    Excel.Excel Column Values Should Be    ${EXCEL_FILE}    ${TYPE_COLUMN}    999

TC09 - End To End With Glue And Download (integration)
    [Documentation]    Trigger Glue → click Complete → download Excel → verify type=1.
    [Tags]    e2e
    ${params}=    Create Dictionary    --env=qa    --load_type=full
    ${run}=       Glue.Trigger Glue Job And Wait For Completion    ${JOB_NAME}    ${params}
    ...           timeout_seconds=1200    poll_interval=30
    Should Be Equal    ${run}[JobRunState]    SUCCEEDED
    ${file}=      Click Complete And Download File    *.xlsx
    ${rows}=      Excel.Read Excel File    ${file}
    Excel.Excel Should Not Be Empty        ${rows}    min_rows=1
    Excel.Excel Column Values Should Be    ${rows}    ${TYPE_COLUMN}    1
