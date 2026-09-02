*** Settings ***
Library     ../libraries/ExcelDataLibrary.py    WITH NAME    Excel
Library     Collections
Library     OperatingSystem

*** Variables ***
${EXCEL_FILE}       ${CURDIR}${/}..${/}testdata${/}output.xlsx
${SHEET}            0
${TYPE_COLUMN}      type
${EXPECTED_TYPE}    1

*** Keywords ***
Load Excel As Dictionaries
    [Documentation]    Reads the Excel file; headers become dictionary keys.
    [Arguments]    ${file}=${EXCEL_FILE}    ${sheet}=${SHEET}    ${header_row}=1
    File Should Exist    ${file}
    ${rows}=    Excel.Read Excel File    ${file}    sheet_name=${sheet}    header_row=${header_row}
    Excel.Excel Should Not Be Empty    ${rows}    min_rows=1
    Log    First row: ${rows}[0]    console=True
    RETURN    ${rows}

Verify Type Column Is Always One
    [Documentation]    Business rule: 'type' must be 1 in every row.
    [Arguments]    ${data}=${EXCEL_FILE}    ${header_row}=1
    ${count}=    Excel.Excel Column Values Should Be    ${data}    ${TYPE_COLUMN}
    ...          ${EXPECTED_TYPE}    header_row=${header_row}
    Log    Verified 'type'=1 in ${count} row(s)    console=True
    RETURN    ${count}
