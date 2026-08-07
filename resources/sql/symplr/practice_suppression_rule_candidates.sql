SELECT DISTINCT TOP ({top_n})
    p.PracticeID,
    COALESCE(p.TaxIDNumber, '') AS TaxIDNumber,

    p2.LocationID,
    COALESCE(p2.NationalProviderID, '') AS NationalProviderID,
    COALESCE(p2.InDirectory, '') AS InDirectory,
    p2.LocationTypeID,

    uf.ParentRecID,
    uf.UserFieldRecID,
    uf.UserDefinedFieldID,
    udf.FieldName,
    COALESCE(uf.Value, '') AS QualifyingValue,
    uf.DateFrom,
    uf.DateTo,

    pt.PracticeTypeName AS LocationTypeName
FROM dbo.Practices p
INNER JOIN dbo.PracticeLocations p2
    ON p2.PracticeID = p.PracticeID
   AND p2.Archived = 'N'

INNER JOIN dbo.UserFields uf
    ON uf.ParentRecID = p2.LocationID
   AND uf.Archived = 'N'

INNER JOIN dbo.UserDefinedFields udf
    ON udf.UserDefinedFieldID = uf.UserDefinedFieldID
   AND udf.Archived = 'N'
   AND udf.FieldName = ?

INNER JOIN dbo.RecordTypes rt
    ON rt.RecordTypeID = udf.RecordTypeID
   AND rt.Archived = 'N'
   AND rt.TableName = 'PracticeLocations'

INNER JOIN dbo.PracticeTypes pt
    ON pt.PracticeTypeID = p2.LocationTypeID
   AND pt.PracticeTypeName = 'Service'
   AND pt.Archived = 'N'

INNER JOIN dbo.StatusSets ss
    ON ss.StatusSetID = pt.StatusSetID
   AND ss.StatusSetName = 'Location Types'

WHERE p.Archived = 'N'
  AND p2.InDirectory = ?
  AND uf.Value IN ({qualifying_value_placeholders})
  AND CAST(uf.DateFrom AS DATE) <= CAST(GETDATE() AS DATE)
  AND (
        uf.DateTo IS NULL
        OR CAST(uf.DateTo AS DATE) >= CAST(GETDATE() AS DATE)
  )

ORDER BY
    p.PracticeID,
    p2.LocationID,
    uf.UserFieldRecID;
