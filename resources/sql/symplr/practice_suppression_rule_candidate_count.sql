SELECT
    COUNT(DISTINCT p2.LocationID) AS CandidateCount
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
  );
