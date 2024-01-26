from marshmallow import Schema, fields


class ArtistFeaturesSchema(Schema):
    id = fields.Str()
    popularity = fields.Integer()
    genres = fields.List(fields.Str())


class AudioFeaturesSchema(Schema):
    id = fields.Str()
    danceability = fields.Float()
    energy = fields.Float()
    loudness = fields.Float()
    speechiness = fields.Float()
    acousticness = fields.Float()
    instrumentalness = fields.Float()
    liveness = fields.Float()
    valence = fields.Float()
    tempo = fields.Float()
    key = fields.Integer()
    mode = fields.Integer()


class TrackFeaturesSchema(Schema):
    id = fields.Str()
    uri = fields.Str()
    name = fields.Str()
    release_date = fields.Str()
    artist_ids = fields.List(fields.Str())
    artist_names = fields.List(fields.Str())
    artist_features = fields.Nested(ArtistFeaturesSchema)  # nested schema
    audio_features = fields.Nested(AudioFeaturesSchema)  # nested schema


class PlaylistFeaturesSchema(Schema):
    artist_schema = ArtistFeaturesSchema()
    audio_schema = AudioFeaturesSchema()
    track_schema = TrackFeaturesSchema()


### Scores
# class ModelScoreMetadata(BaseModel):
#     score: float
#     _score_validation = validator("score", allow_reuse=True)(
#         validate_score,
#     )


### Metrics
# class ModelMetrics(BaseModel):
#     auroc: float
#     gini: float
#
#
# class DataMetrics(BaseModel):
#     correlation: list[tuple[str, ...]]
#     feature_importance: dict[str, float]
#
# Metrics = Union[OverdraftDataMetrics, OverdraftModelMetrics]


### Training/Validation/Optimization
# class ModelMetricsGroup(BaseModel):
#     train: Optional[Metrics]
#     test: Optional[Metrics]
#     validation_01: Optional[Metrics]
#     validation_02: Optional[Metrics]
#
#
# class ModelEstimatorParams(BaseModel):
#     tx: Optional[dict[str, Any]]
#     integration: Optional[dict[str, Any]]
#
#
# class OverdraftMetricsCollection(BaseModel):
#     tx: Optional[OverdraftMetricsGroup]
#     integration: Optional[OverdraftMetricsGroup]
#
# class Metadata(BaseModel):
#     metrics_model: OverdraftMetricsCollection
#     metrics_data: OverdraftMetricsCollection
#     estimator_params: OverdraftEstimatorParams
#     features_date_ref: list[str]
