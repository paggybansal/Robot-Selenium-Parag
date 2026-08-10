/*
Rule 9 — Count unique eligible PractitionerLocation records.

Bound parameters, in exact order:
    1. Service
    2. Billing
    3. Practice type
    4. Urgent Care Center
    5. Location Verification Status
    6. Correct
    7. Y
*/

SELECT
    COUNT(DISTINCT pl.PractitionerLocationRecID) AS CandidateCount
FROM dbo.PractitionerLocations AS pl

INNER JOIN dbo.Practitioners AS p
    ON p.PractitionerID = pl.PractitionerID
   AND p.Archived = 'N'

INNER JOIN dbo.PracticeLocations AS pl_service
    ON pl_service.LocationID = pl.LocationID
   AND pl_service.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS service_practice_type
    ON service_practice_type.PracticeTypeID = pl_service.LocationTypeID
   AND service_practice_type.Archived = 'N'
   AND service_practice_type.PracticeTypeName = ?

INNER JOIN dbo.PracticeLocations AS pl_billing
    ON pl_billing.PracticeID = pl_service.PracticeID
   AND pl_billing.NationalProviderID = pl_service.NationalProviderID
   AND pl_billing.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS billing_practice_type
    ON billing_practice_type.PracticeTypeID = pl_billing.LocationTypeID
   AND billing_practice_type.Archived = 'N'
   AND billing_practice_type.PracticeTypeName = ?

INNER JOIN dbo.LocationServices AS ls
    ON ls.LocationID = pl_billing.LocationID
   AND ls.Archived = 'N'

INNER JOIN dbo.ServiceTypes AS st
    ON st.ServiceTypeID = ls.ServiceTypeID
   AND st.Archived = 'N'
   AND st.ServiceTypeName = ?

INNER JOIN dbo.ServiceCategoryTypes AS sct
    ON sct.ServiceCategoryTypeID = ls.ServiceCategoryTypeID
   AND sct.Archived = 'N'
   AND sct.ServiceCategoryTypeName = ?

INNER JOIN dbo.UserFields AS location_status_uf
    ON location_status_uf.ParentRecID = pl.PractitionerLocationRecID
   AND location_status_uf.Archived = 'N'

INNER JOIN dbo.UserDefinedFields AS location_status_udf
    ON location_status_udf.UserDefinedFieldID =
       location_status_uf.UserDefinedFieldID
   AND location_status_udf.Archived = 'N'
   AND location_status_udf.FieldName = ?

INNER JOIN dbo.UserDefinedListFields AS location_status_udlf
    ON location_status_udlf.UserDefinedFieldID =
       location_status_udf.UserDefinedFieldID
   AND location_status_udlf.UserDefinedListFieldID =
       location_status_uf.UserDefinedListFieldID
   AND location_status_udlf.Archived = 'N'
   AND location_status_udlf.Value = ?

WHERE pl.Archived = 'N'
  AND pl.InDirectory = ?;
