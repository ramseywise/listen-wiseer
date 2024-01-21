import pandas as pd

### this should include functions to load data from DB
# class Dataset(SqlDataset):
#     def load(self) -> pd.DataFrame:
#         """Loads Credit Bureau infer class dataset.
#
#         Returns:
#             pd.DataFrame: Credit Bureau infer dataset as dataframe
#         """
#         return self.read_data(
#             config.data_location.cb_inference_path,
#             config.data_location.is_local_path,
#         ).set_index("user_id")
