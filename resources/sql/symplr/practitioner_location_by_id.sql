/*
Rule 9 final-state validation.

Parameter:
    1. PractitionerLocationRecID

Expected post-Dataloader result:
    dbo.PractitionerLocations.InDirectory = 'N'
*/

SELECT
    p.PractitionerID,

    COALESCE(
        CONVERT(VARCHAR(50), p.NationalProviderID),
        ''
    ) AS NationalProviderID,

    pl.PractitionerLocationRecID,
    pl.LocationID,
    COALESCE(pl.InDirectory, '') AS InDirectory,

    p.Archived AS PractitionerArchived,
    pl.Archived AS PractitionerLocationArchived
FROM dbo.PractitionerLocations AS pl
INNER JOIN dbo.Practitioners AS p
    ON p.PractitionerID = pl.PractitionerID
WHERE pl.PractitionerLocationRecID = ?
  AND p.Archived = 'N'
  AND pl.Archived = 'N';
