/*
Rule 9 — Urgent Care Practitioner Location Suppression

A PractitionerLocation qualifies when:

1. PractitionerLocations.InDirectory = 'Y'

2. The PractitionerLocation is tied to a Service PracticeLocation.

3. The Service PracticeLocation has a corresponding Billing PracticeLocation
   for the same PracticeID and NationalProviderID.

4. The Billing PracticeLocation has a LocationService where:
       ServiceTypeName         = 'Practice type'
       ServiceCategoryTypeName = 'Urgent Care Center'

5. The PractitionerLocation has an active User Defined List field:
       FieldName = 'Location Verification Status'
       Value     = 'Correct'

Dynamic tokens:
    {top_n}

Bound parameters, in exact order:
    1. Service
    2. Billing
    3. Practice type
    4. Urgent Care Center
    5. Location Verification Status
    6. Correct
    7. Y
*/

SELECT DISTINCT TOP ({top_n})
    p.PractitionerID,
    COALESCE(
        CONVERT(VARCHAR(50), p.NationalProviderID),
        ''
    ) AS NationalProviderID,

    pl.PractitionerLocationRecID,
    pl.LocationID AS PractitionerLocationID,
    COALESCE(pl.MemberTypeID, 0) AS MemberTypeID,
    COALESCE(pl.InDirectory, '') AS InDirectory,

    pl_service.PracticeID,
    pl_service.LocationID AS ServiceLocationID,
    service_practice_type.PracticeTypeName AS ServiceLocationTypeName,

    pl_billing.LocationID AS BillingLocationID,
    billing_practice_type.PracticeTypeName AS BillingLocationTypeName,

    ls.LocationServiceRecID,
    st.ServiceTypeName,
    sct.ServiceCategoryTypeName,

    location_status_udlf.Value AS LocationVerificationStatus

FROM dbo.PractitionerLocations AS pl

INNER JOIN dbo.Practitioners AS p
    ON p.PractitionerID = pl.PractitionerID
   AND p.Archived = 'N'

/*
Practitioner location must be attached to a Service PracticeLocation.
*/
INNER JOIN dbo.PracticeLocations AS pl_service
    ON pl_service.LocationID = pl.LocationID
   AND pl_service.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS service_practice_type
    ON service_practice_type.PracticeTypeID = pl_service.LocationTypeID
   AND service_practice_type.Archived = 'N'
   AND service_practice_type.PracticeTypeName = ?

/*
Locate the matching Billing PracticeLocation for the same Practice and NPI.
*/
INNER JOIN dbo.PracticeLocations AS pl_billing
    ON pl_billing.PracticeID = pl_service.PracticeID
   AND pl_billing.NationalProviderID = pl_service.NationalProviderID
   AND pl_billing.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS billing_practice_type
    ON billing_practice_type.PracticeTypeID = pl_billing.LocationTypeID
   AND billing_practice_type.Archived = 'N'
   AND billing_practice_type.PracticeTypeName = ?

/*
Urgent Care classification exists on LocationServices for the Billing location.
*/
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

/*
Developer-confirmed Location Verification Status condition.

This INNER JOIN is logically equivalent to the developer's EXISTS condition.
DISTINCT protects candidate output if duplicate active UDF rows exist.
*/
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
  AND pl.InDirectory = ?

ORDER BY
    p.PractitionerID,
    pl.PractitionerLocationRecID,
    ls.LocationServiceRecID;
