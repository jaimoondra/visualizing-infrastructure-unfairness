from datetime import datetime
import geopandas as gpd
import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.constants import DEFAULT_POVERTY_THRESHOLD, DEFAULT_RURAL_DISTANCE_THRESHOLD, DEFAULT_URBAN_DISTANCE_THRESHOLD
from src.usa.constants import state_names, interesting_states
from src.usa.states import USAState
from src.usa.facilities import CVS, Walgreens, Walmart, UrgentCare, Hospitals, NursingHomes, ChildCare, PrivateSchools, FDICInsuredBanks, PharmaciesTop3
from src.usa.utils import racial_labels, compute_medical_deserts, get_page_url, get_demographic_data
from src.usa.plot_utils import plot_state, plot_stacked_bar, plot_existing_facilities, plot_blockgroups, plot_voronoi_cells


st.set_page_config(layout='wide', initial_sidebar_state='collapsed', page_title='medical-facility-deserts')

st.sidebar.caption('This tool aims to identify facility deserts in the US – poorer areas with low '
                   'access to various critical facilities such as pharmacies, hospitals, and schools.')


def get_disproportionately_affected_racial_groups(demographics_all, demographics_deserts):
    def is_disproportionately_affected(fraction_all, fraction_deserts, n_deserts):
        more_than_five_deserts = (n_deserts >= 5)
        four_times_more_deserts = fraction_deserts > 4 * fraction_all
        over_ten_percent_difference = fraction_deserts - fraction_all > 0.1
        if more_than_five_deserts and (four_times_more_deserts or over_ten_percent_difference):
            return True
        else:
            return False

    n_blockgroups = sum(demographics_all.values())
    n_deserts = sum(demographics_deserts.values())

    disproportionately_affected_racial_groups = []
    for racial_label in demographics_all.keys():
        if racial_label in demographics_deserts.keys():
            fraction_all = demographics_all[racial_label]/n_blockgroups
            fraction_deserts = demographics_deserts[racial_label]/n_deserts
            if is_disproportionately_affected(fraction_all, fraction_deserts, demographics_deserts[racial_label]):
                disproportionately_affected_racial_groups.append(racial_label)

    return disproportionately_affected_racial_groups


def get_facility_from_facility_name(facilities, facility_name):
    for facility in facilities:
        if facility.display_name == facility_name:
            return facility


def state_of_the_day(state_names):
    day_of_year = datetime.now().timetuple().tm_yday
    state_of_the_day = state_names[day_of_year % len(state_names)]
    return state_of_the_day


facilities = [PharmaciesTop3, UrgentCare, Hospitals, NursingHomes, PrivateSchools, FDICInsuredBanks, ChildCare]
facility_display_names = [facility.display_name for facility in facilities]

col_left, col_center, col_right = st.columns([1, 3, 1])

with col_left:
    def update_facility_display_name():
        st.session_state['facility_display_name'] = st.session_state['facility_display_name_new']

    if 'facility_display_name' in st.session_state:
        facility_display_name = st.session_state['facility_display_name']
        index = facility_display_names.index(facility_display_name)
    else:
        index = 0
    facility_display_name = st.selectbox(label='Choose a facility', options=facility_display_names, index=index, key='facility_display_name_new',
                                         help='Select the type of facility to analyze', on_change=update_facility_display_name)
    facility = get_facility_from_facility_name(facilities, facility_display_name)

    def update_state_name():
        st.session_state['state_name'] = st.session_state['state_name_new']

    state_of_the_day = state_of_the_day(interesting_states)
    if 'state_name' in st.session_state:
        state_of_the_day = st.session_state['state_name']
    state_name = st.selectbox('Choose a US state', options=state_names, index=state_names.index(state_of_the_day), key='state_name_new', on_change=update_state_name)

    State = USAState(state_name)
    state_fips = State.fips
    state_abbr = State.abbreviation

with col_center:
    st.markdown("""
        <h1 style="font-size: 40px; text-align: center; margin-bottom: 0em; margin-top: 0em; line-height: 1.0;">
            """ + facility.type.capitalize() + """ deserts in
            <span style="color: #c41636">
                """ + state_name + """
            </span>
        </h1>
        <h3 style="font-size: 18px; text-align: center; margin-top: 0em;">
            Based on distances to <span style="color: #c41636">""" + facility.display_name.lower() + """</span>
        </h3>
        """, unsafe_allow_html=True)

st.markdown(facility.get_message(), unsafe_allow_html=True)

with col_left:
    def update_poverty_threshold():
        st.session_state['poverty_threshold'] = st.session_state['poverty_threshold_new']

    with st.container(border=True):
        if 'poverty_threshold' in st.session_state:
            poverty_threshold = st.session_state['poverty_threshold']
        else:
            poverty_threshold = DEFAULT_POVERTY_THRESHOLD
        poverty_threshold = st.slider(r'Choose poverty threshold $p$%', min_value=0, max_value=100, step=5, key='poverty_threshold_new',
                                      value=poverty_threshold, help='Only blockgroups with over $p$% of the population below the poverty line are considered ' + facility.type + ' deserts.',
                                      on_change=update_poverty_threshold)

    def update_urban_distance_threshold():
        st.session_state['urban_distance_threshold'] = st.session_state['urban_distance_threshold_new']

    def update_rural_distance_threshold():
        st.session_state['rural_distance_threshold'] = st.session_state['rural_distance_threshold_new']

    with st.container(border=True):
        st.write('Choose distance threshold $n$ miles')
        col_side1, col_side2 = st.columns(2)
        if 'urban_distance_threshold' in st.session_state:
            urban_distance_threshold = st.session_state['urban_distance_threshold']
        else:
            urban_distance_threshold = DEFAULT_URBAN_DISTANCE_THRESHOLD
        urban_distance_threshold = col_side1.slider(r'For urban areas', min_value=0.0, max_value=15.0, step=0.5,
                                                    value=urban_distance_threshold, format='%.1f', key='urban_distance_threshold_new',
                                                    help='Distance threshold for urban areas; only blockgroups further than this distance from the nearest facility are considered ' + facility.type + ' deserts.',
                                                    on_change=update_urban_distance_threshold)

        if 'rural_distance_threshold' in st.session_state:
            rural_distance_threshold = st.session_state['rural_distance_threshold']
        else:
            rural_distance_threshold = DEFAULT_RURAL_DISTANCE_THRESHOLD
        rural_distance_threshold = col_side2.slider(r'For rural areas', min_value=0.0, max_value=30.0, step=1.0,
                                                    value=rural_distance_threshold, format='%.1f', key='rural_distance_threshold_new',
                                                    help='Distance threshold for rural areas; only blockgroups further than this distance from the nearest facility are considered ' + facility.type + ' deserts.',
                                                    on_change=update_rural_distance_threshold)


with col_right:
    st.caption(f'**Figure**: Census blockgroups classified as ' + facility.type + ' deserts in ' + state_name
               + '. Colored by racial/ethnic majority.')

    show_deserts = st.toggle(facility.type.capitalize() + ' deserts', value=True)
    show_facility_locations = st.toggle(facility.display_name, value=False)
    show_voronoi_cells = st.toggle('''[Voronoi](https://en.wikipedia.org/wiki/Voronoi_diagram) cells''', value=False)

    # with st.popover('Figure options', use_container_width=True):
    #     show_deserts = st.checkbox('Show ' + facility.type + ' deserts', value=True)
    #     show_facility_locations = st.checkbox('Show ' + facility.display_name.lower(), value=False)
    #     show_voronoi_cells = st.checkbox('''Show [Voronoi](https://en.wikipedia.org/wiki/Voronoi_diagram) cells''', value=False)


with col_center:
    census_df = State.get_census_data(level='blockgroup')

    fig = go.Figure()
    fig, bounds = plot_state(fig, State)

    distance_label = facility.distance_label
    desert_df = compute_medical_deserts(census_df, poverty_threshold, urban_distance_threshold, rural_distance_threshold, distance_label)
    if show_deserts:
        fig = plot_blockgroups(fig, desert_df)

    if show_facility_locations:
        if facility.name == 'top_3_pharmacy_chains':
            for pharmacy_chain in [CVS, Walgreens, Walmart]:
                fig = plot_existing_facilities(fig, pharmacy_chain, bounds)
        else:
            fig = plot_existing_facilities(fig, facility, bounds)

    if show_voronoi_cells:
        fig = plot_voronoi_cells(fig, facility, state_fips)

    config = {
        'modeBarButtonsToRemove': ['zoomOut', 'select2d'],
        'staticPlot': False,
        'scrollZoom': True,
        'toImageButtonOptions': {
            'format': 'png',
            'scale': 1.5,
            'filename': facility.type + '_deserts_' + state_abbr + '_' + facility.name + '.png',
        }
    }

    st.plotly_chart(fig, use_container_width=True, config=config)

with col_right:
    # st.caption(f'**Figure**: Census blockgroups classified as ' + facility.type + ' deserts in ' + state_name
    #            + '. Colored by racial/ethnic majority.')

    legend_labels = {
        'white_alone': 'Majority White',
        'black_alone': 'Majority Black',
        'aian_alone': 'Majority AIAN',
        'asian_alone': 'Majority Asian',
        'nhopi_alone': 'Majority NHOPI',
        'hispanic': 'Majority Hispanic',
        'other': 'Other',
    }

    demographics_all = get_demographic_data(census_df, racial_labels)
    n_blockgroups = len(census_df)

    demographics_deserts = get_demographic_data(desert_df, racial_labels)

    fig1, fig2 = plot_stacked_bar(demographics_all), plot_stacked_bar(demographics_deserts)

    st.markdown('''<center>''' + state_name + ''' has <b>''' + str(len(census_df)) + '''</b> blockgroups</center>''', unsafe_allow_html=True)
    st.plotly_chart(fig1, use_container_width=True, config={'displayModeBar': False})
    st.markdown('''<center><b>''' + str(len(desert_df)) + '''</b> are ''' + facility.type + ''' deserts</center>''', unsafe_allow_html=True)
    st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})

    disproportionately_affected_racial_groups = get_disproportionately_affected_racial_groups(demographics_all, demographics_deserts)
    for racial_label in disproportionately_affected_racial_groups:
        fraction_all = demographics_all[racial_label]/n_blockgroups
        percent_all = str(round(fraction_all * 100, 2))

        fraction_deserts = demographics_deserts[racial_label]/len(desert_df)
        percent_deserts = str(round(fraction_deserts * 100, 2))

        with st.container(border=True):
            st.write(legend_labels[racial_label] + ' blockgroups make up :red[' + percent_deserts + '%] of ' +
                     facility.type + ' deserts in ' + state_name + ' while being only :blue[' + percent_all +
                     '%] of all blockgroups.')

    # if len(desert_df) > 0:
    #     for racial_label in racial_labels:
    #         if racial_label in demographics_all and racial_label in demographics_deserts and racial_label != 'other':
    #             fraction_of_all_blockgroups = demographics_all[racial_label]/n_blockgroups
    #             fraction_of_medical_deserts = demographics_deserts[racial_label]/len(desert_df)
    #
    #             four_times_deserts = fraction_of_medical_deserts> 4 * fraction_of_all_blockgroups
    #             over_ten_percent_difference = fraction_of_medical_deserts - fraction_of_all_blockgroups > 0.1
    #             over_five_deserts = fraction_of_medical_deserts * len(desert_df) >= 5
    #
    #             if over_five_deserts and (four_times_deserts or over_ten_percent_difference):
    #                 overall_percent_str = str(round(fraction_of_all_blockgroups * 100, 2))
    #                 desert_percent_str = str(round(fraction_of_medical_deserts * 100, 2))
    #                 with st.container(border=True):
    #                     st.write(legend_labels[racial_label] + ' blockgroups may be disproportionately affected by '
    #                              + facility.type + ' deserts in ' + state_name + ': they make up :red[' + desert_percent_str +
    #                              '%] of ' + facility.type + ' deserts in ' + state_name + ' while being only :blue[' +
    #                              overall_percent_str + '%] of all blockgroups.')

    url = get_page_url('suggesting-new-facilities')
    st.markdown(
        '''
        We also created a [tool](''' + url + ''') that suggests locations for new facilities to 
        reduce the impact of ''' + facility.type + ''' deserts.'''.format(facility.type), unsafe_allow_html=True
    )

with col_left:
    move_to_explanation = st.button('Explanation', use_container_width=True)
    if move_to_explanation:
        st.switch_page("pages/explainer.py")

    move_to_suggesting_facilities = st.button('Suggesting new facilities', use_container_width=True)
    if move_to_suggesting_facilities:
        st.switch_page("pages/suggesting-new-facilities.py")


st.sidebar.caption('Created by Swati Gupta, [Jai Moondra](https://jaimoondra.github.io/), Mohit Singh.\n'
                   'Based on our [paper](https://arxiv.org/abs/2211.14873) on fairness in facility location.\n'
                   'Submit any feedback to [jmoondra3@gatech.edu](mailto:jmoondra3@gatech.edu).\n')

st.sidebar.caption('We assume straight-line distances, and the accuracy of our results depends on the accuracy of the underlying data. '
                   'The maps are approximate.')