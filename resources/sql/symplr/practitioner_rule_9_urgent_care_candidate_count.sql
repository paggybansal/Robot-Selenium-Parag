/*
Rule 9 — Count unique PractitionerLocation candidates.
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
   AND pl_service.LocationTypeID IN (
        SELECT pt.PracticeTypeID
        FROM dbo.PracticeTypes AS pt
        WHERE pt.PracticeTypeName = 'Service'
          AND pt.Archived = 'N'
   )

INNER JOIN dbo.PracticeLocations AS pl_billing
    ON pl_billing.NationalProviderID = pl_service.NationalProviderID
   AND pl_billing.PracticeID = pl_service.PracticeID
   AND pl_billing.Archived = 'N'
   AND pl_billing.LocationTypeID IN (
        SELECT pt.PracticeTypeID
        FROM dbo.PracticeTypes AS pt
        WHERE pt.PracticeTypeName = 'Billing'
          AND pt.Archived = 'N'
   )

INNER JOIN dbo.LocationServices AS ls
    ON ls.LocationID = pl_billing.LocationID
   AND ls.Archived = 'N'

INNER JOIN dbo.ServiceTypes AS st
    ON st.ServiceTypeID = ls.ServiceTypeID
   AND st.Archived = 'N'
   AND st.ServiceTypeName = 'Practice type'

INNER JOIN dbo.ServiceCategoryTypes AS sct
    ON sct.ServiceCategoryTypeID = ls.ServiceCategoryTypeID
   AND sct.Archived = 'N'
   AND sct.ServiceCategoryTypeName = 'Urgent Care Center'

WHERE pl.Archived = 'N'
  AND pl.InDirectory = 'Y'

  AND p.NationalProviderID IS NOT NULL

  AND EXISTS (
        SELECT 1
        FROM dbo.UserFields AS uf

        INNER JOIN dbo.UserDefinedFields AS udf
            ON udf.UserDefinedFieldID = uf.UserDefinedFieldID
           AND udf.Archived = 'N'

        INNER JOIN dbo.UserDefinedListFields AS udlf
            ON udlf.UserDefinedFieldID = udf.UserDefinedFieldID
           AND udlf.UserDefinedListFieldID = uf.UserDefinedListFieldID
           AND udlf.Archived = 'N'

        WHERE uf.ParentRecID = pl.PractitionerLocationRecID
          AND uf.Archived = 'N'
          AND udf.FieldName = 'Location Verification Status'
          AND udlf.Value = 'Correct'
  );
