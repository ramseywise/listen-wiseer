# Listen-Wiseer

Listen-Wiser is a music analytics Flask application that leverages the Spotify API for generating playlists based on personalized recommendations.

## Contents

src
   |-- app.py
   |-- analysis
   |   |-- data.py
   |   |-- eda.ipynb
   |   |-- genre.py
   |   |-- output/*
   |   |-- plotting.py
   |-- api
   |   |-- playlists.py
   |   |-- spotify_client.py
   |-- models
   |   |-- classifiers.py
   |   |-- clustering.py
   |   |-- cosine.py
   |   |-- euclidean.py
   |   |-- schema.py
   |   |-- settings.py
   |-- utils
   |    |-- config.py
   |    |-- const.py
   |    |-- logger.py

### 1 | Run app
The main script for this application takes us through the authorization process, which requires authentication (whereby the user has to first log in to grant scope of permissions). Once the user is authenticated, they are then given a response code that is traded in for an access token, which is necessary for accessing Spotify API. Main functionality of this script is to get access, make API requests to get data and returns recommendations for playlists.

### 2 | Request Spotify API
The first component of this application was setting up a spotify developer's account and accessing api with Spotify client id and client secret. Next, I added a data pipeline to request track features for my playlists and transform these features into a dataframe ready for modeling. Note that the Spotify API has numerous helpful resources for content-based recommendations using genre or retreiving similar artists and new releases from my artists. Other potential avenues that will be included in later versions include user-listening history.

### 3 | Analysis 
Analysis was also performed on this data, which not only compared the feature distributions provided by the Spotify API, but also including an outlier anlaysis of tracks for each playlist in order to remove any tracks that did not fit the playlist. I implented statistical methods for identifying outliers before switching to Isolation Forest, which does fairly well with identifying anomalies within small data sets and had comparable output to the statistical outliers. Furthermore, if allows to automate this process in the future, where decisions to keep or drop tracks from a playlist will continue to improve the algorithm.

#### Genre Classification
Another component of this application was creating a genre map in order to utilize the genre feature provided by Spotify API in model recommendations. My playlist contained over 2k unique genres that I was able to map to my top 16 genres, which were then further reduced to 4 genres (electronic, acoustic, instrumental and dance). For example, acoustic is my largest genre group and composed of subgenres such as rock, indie, soul, blues. These are then further refined to more specific genres, such as "classic rock", "krautrock" or "art rock".

My first attempt at genre classification began with simple NLP exercise: search and classify genres based on their text. For example, the similarity calculation I used to classify the examples above would result positively in finding "rock" being the underscoring genre of these. However, validating this approach quickly proved difficult. How do you classify "soul jazz"? Is it soul? Is it jazz? At least this example is somewhat clearly a hybrid of of somewhat similar genres. But what happens when you have "ambient" genre, which is drastically different with "ambient folk" or "ambient idm". For modeling purposes, this approach was not the way to go for content-based recommendations.

Limitations to data size also prevented successful attempts to classify the genre categories with quantitative methods. I calculated distanced between genres using various features and implented hierchical, kmeans and spectral clustering and t-sne dimensionality reduction methods to try and account for other mechanisms distinguishing between genre groups. From this point, I sought Every Noise at Once, an awesome genre mapping project that aimed to reduce dimensionality of genre features to a simple x, y axis with a color scheme for the purpose of visualizing these relationships. The advantage of using this methodology is that they are comparing over 6,000 genres to understand the distance or similarity between genre groups and therefore are an excellent means for validating my own genre mapping scheme. For more information, see the output from src/analysis. 

## 4 | Recommendation Models
TBD

## 5 | DB
The next step before implementing the model pipeline is to build a postgres DB that stores track, artist and audio features from my playlists. By storing and updating the output over time, this information will provide a personalized feedback loop to filter future recommendations.