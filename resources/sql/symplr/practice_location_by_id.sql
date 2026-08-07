SELECT
    p.PracticeID,
    COALESCE(p.TaxIDNumber, '') AS TaxIDNumber,

    p2.LocationID,
    COALESCE(p2.NationalProviderID, '') AS NationalProviderID,
    COALESCE(p2.InDirectory, '') AS InDirectory,
    p2.LocationTypeID,

    pt.PracticeTypeName AS LocationTypeName,

    p.Archived AS PracticeArchived,
    p2.Archived AS PracticeLocationArchived
FROM dbo.Practices p
INNER JOIN dbo.PracticeLocations p2
    ON p2.PracticeID = p.PracticeID
INNER JOIN dbo.PracticeTypes pt
    ON pt.PracticeTypeID = p2.LocationTypeID
WHERE p2.LocationID = ?
  AND p.Archived = 'N'
  AND p2.Archived = 'N';
