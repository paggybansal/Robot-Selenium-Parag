/*
Rule 9 — Urgent Care Practitioner Location suppression.

A PractitionerLocation qualifies when:

1. PractitionerLocations.InDirectory = 'Y'

2. PractitionerLocation is associated with a Service PracticeLocation.

3. The Service PracticeLocation has a matching Billing PracticeLocation
   for the same PracticeID and NationalProviderID.

4. The Billing PracticeLocation has LocationServices where:
       ServiceTypeName = 'Practice type'
       ServiceCategoryTypeName = 'Urgent Care Center'

5. PractitionerLocation has:
       Location Verification Status = 'Correct'

The NPI condition is included because Rule 9 StatusDB validation requires:

    process_id + NationalProviderID
*/

SELECT DISTINCT TOP ({top_n})
    p.PractitionerID,

    COALESCE(
        CONVERT(VARCHAR(50), p.NationalProviderID),
        ''
    ) AS NationalProviderID,

    pl.PractitionerLocationRecID,
    pl.LocationID AS PractitionerLocationID,

    COALESCE(pl.InDirectory, '') AS InDirectory,
    COALESCE(pl.MemberTypeID, 0) AS MemberTypeID,

    pl_service.PracticeID,
    pl_service.LocationID AS ServiceLocationID,
    service_practice_type.PracticeTypeName AS ServiceLocationTypeName,

    pl_billing.LocationID AS BillingLocationID,
    billing_practice_type.PracticeTypeName AS BillingLocationTypeName,

    ls.LocationServiceRecID,
    st.ServiceTypeName,
    sct.ServiceCategoryTypeName,

    location_verification_udlf.Value AS LocationVerificationStatus

FROM dbo.PractitionerLocations AS pl

INNER JOIN dbo.Practitioners AS p
    ON p.PractitionerID = pl.PractitionerID
   AND p.Archived = 'N'

/* Practitioner service location */
INNER JOIN dbo.PracticeLocations AS pl_service
    ON pl_service.LocationID = pl.LocationID
   AND pl_service.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS service_practice_type
    ON service_practice_type.PracticeTypeID = pl_service.LocationTypeID
   AND service_practice_type.PracticeTypeName = 'Service'

/* Matching practice billing location */
INNER JOIN dbo.PracticeLocations AS pl_billing
    ON pl_billing.NationalProviderID = pl_service.NationalProviderID
   AND pl_billing.PracticeID = pl_service.PracticeID
   AND pl_billing.Archived = 'N'

INNER JOIN dbo.PracticeTypes AS billing_practice_type
    ON billing_practice_type.PracticeTypeID = pl_billing.LocationTypeID
   AND billing_practice_type.PracticeTypeName = 'Billing'

/* Urgent Care classification on Billing Location */
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

/* Location Verification Status = Correct */
INNER JOIN dbo.UserFields AS location_verification_uf
    ON location_verification_uf.ParentRecID =
       pl.PractitionerLocationRecID
   AND location_verification_uf.Archived = 'N'

INNER JOIN dbo.UserDefinedFields AS location_verification_udf
    ON location_verification_udf.UserDefinedFieldID =
       location_verification_uf.UserDefinedFieldID
   AND location_verification_udf.Archived = 'N'
   AND location_verification_udf.FieldName =
       'Location Verification Status'

INNER JOIN dbo.UserDefinedListFields AS location_verification_udlf
    ON location_verification_udlf.UserDefinedFieldID =
       location_verification_udf.UserDefinedFieldID
   AND location_verification_udlf.UserDefinedListFieldID =
       location_verification_uf.UserDefinedListFieldID
   AND location_verification_udlf.Archived = 'N'
   AND location_verification_udlf.Value = 'Correct'

WHERE pl.Archived = 'N'
  AND pl.InDirectory = 'Y'

  /* Required for StatusDB process_id + NPI validation */
  AND NULLIF(
        LTRIM(RTRIM(CONVERT(VARCHAR(50), p.NationalProviderID))),
        ''
  ) IS NOT NULL

ORDER BY
    p.PractitionerID,
    pl.PractitionerLocationRecID,
    ls.LocationServiceRecID;
